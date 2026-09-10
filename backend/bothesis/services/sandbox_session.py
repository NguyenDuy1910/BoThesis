"""Persist recovery metadata for provider-backed conversation sandboxes."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.db.models import Conversation, SandboxSession
from bothesis.services import (
    AuthContext,
    DocumentNotFoundError,
    SandboxManifestResource,
    SandboxProviderFile,
    SandboxSessionState,
)


class SandboxSessionService:
    """Own durable sandbox identity, recovery manifest, and opaque bindings.

    This service deliberately does not create a provider container or transfer
    file bytes. Those are request-scoped adapter operations. It records only
    enough metadata to resume a provider workspace or rebuild it from durable
    Item resources after the provider environment has expired.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def active(
        self,
        access: AuthContext,
        *,
        conversation_id: UUID,
        provider: str,
    ) -> SandboxSessionState | None:
        """Return the caller's current provider binding, without creating one."""

        tenant_id = _tenant_id(access)
        normalized_provider = _provider(provider)
        async with self._sessions() as session:
            await _conversation(session, access, conversation_id)
            row = await session.scalar(
                select(SandboxSession).where(
                    SandboxSession.conversation_id == conversation_id,
                    SandboxSession.tenant_id == tenant_id,
                    SandboxSession.user_id == access.user_id,
                    SandboxSession.provider == normalized_provider,
                    SandboxSession.status == "active",
                    SandboxSession.deleted_at.is_(None),
                )
                .order_by(SandboxSession.updated_at.desc())
                .limit(1)
            )
        return _state(row) if row is not None else None

    async def recoverable(
        self,
        access: AuthContext,
        *,
        conversation_id: UUID,
        provider: str,
    ) -> SandboxSessionState | None:
        """Return the newest expired manifest after rechecking conversation access."""

        tenant_id = _tenant_id(access)
        normalized_provider = _provider(provider)
        async with self._sessions() as session:
            await _conversation(session, access, conversation_id)
            row = await session.scalar(
                select(SandboxSession)
                .where(
                    SandboxSession.conversation_id == conversation_id,
                    SandboxSession.tenant_id == tenant_id,
                    SandboxSession.user_id == access.user_id,
                    SandboxSession.provider == normalized_provider,
                    SandboxSession.status == "expired",
                    SandboxSession.deleted_at.is_(None),
                )
                .order_by(SandboxSession.updated_at.desc())
                .limit(1)
            )
        return _state(row) if row is not None else None

    async def ensure(
        self,
        access: AuthContext,
        *,
        conversation_id: UUID,
        provider: str,
    ) -> SandboxSessionState:
        """Return or lazily create the sole active sandbox for this provider."""

        tenant_id = _tenant_id(access)
        normalized_provider = _provider(provider)
        async with self._sessions.begin() as session:
            await _conversation(session, access, conversation_id, lock=True)
            row = await session.scalar(
                select(SandboxSession)
                .where(
                    SandboxSession.conversation_id == conversation_id,
                    SandboxSession.tenant_id == tenant_id,
                    SandboxSession.user_id == access.user_id,
                    SandboxSession.provider == normalized_provider,
                    SandboxSession.status == "active",
                    SandboxSession.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if row is None:
                row = SandboxSession(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    user_id=access.user_id,
                    provider=normalized_provider,
                    manifest={"resources": []},
                    provider_state={"materialized_files": [], "observed_files": []},
                    last_used_at=datetime.now(UTC),
                )
                session.add(row)
                await session.flush()
            else:
                row.last_used_at = datetime.now(UTC)
                await session.flush()
            return _state(row)

    async def record_materialization(
        self,
        access: AuthContext,
        *,
        session_id: UUID,
        resource: SandboxManifestResource,
        provider_file: SandboxProviderFile,
    ) -> SandboxSessionState:
        """Record a successfully uploaded durable resource for workspace rebuild."""

        async with self._sessions.begin() as session:
            row = await _active_session(session, access, session_id)
            resources = list(_manifest_resources(row.manifest))
            if not any(item.resource_id == resource.resource_id for item in resources):
                resources.append(resource)
            files = list(_provider_files(row.provider_state, "materialized_files"))
            files = [item for item in files if item.resource_id != resource.resource_id]
            files.append(provider_file)
            row.manifest = {"resources": [_resource_payload(item) for item in resources]}
            row.provider_state = _provider_state(
                row.provider_state,
                materialized_files=files,
            )
            row.last_used_at = datetime.now(UTC)
            await session.flush()
            return _state(row)

    async def record_resource(
        self,
        access: AuthContext,
        *,
        session_id: UUID,
        resource: SandboxManifestResource,
    ) -> SandboxSessionState:
        """Add a durable resource to the rebuild manifest without a provider call."""

        async with self._sessions.begin() as session:
            row = await _active_session(session, access, session_id)
            resources = list(_manifest_resources(row.manifest))
            if not any(item.resource_id == resource.resource_id for item in resources):
                resources.append(resource)
                row.manifest = {
                    "resources": [_resource_payload(item) for item in resources]
                }
            row.last_used_at = datetime.now(UTC)
            await session.flush()
            return _state(row)

    async def record_execution(
        self,
        access: AuthContext,
        *,
        session_id: UUID,
        environment_id: str,
        files: Iterable[SandboxProviderFile],
    ) -> SandboxSessionState:
        """Persist the latest provider environment and observable workspace files."""

        normalized_environment = _identifier(environment_id, "sandbox environment")
        observed = _unique_files(files)
        async with self._sessions.begin() as session:
            row = await _active_session(session, access, session_id)
            row.provider_state = _provider_state(
                row.provider_state,
                environment_id=normalized_environment,
                observed_files=observed,
            )
            row.last_used_at = datetime.now(UTC)
            await session.flush()
            return _state(row)

    async def expire(
        self,
        access: AuthContext,
        *,
        session_id: UUID,
    ) -> None:
        """Tombstone a provider binding that can no longer be resumed."""

        async with self._sessions.begin() as session:
            row = await _active_session(session, access, session_id)
            row.status = "expired"
            row.last_used_at = datetime.now(UTC)


def _tenant_id(access: AuthContext) -> UUID:
    if access.tenant_id is None:
        raise DocumentNotFoundError("sandbox session not found")
    return access.tenant_id


def _provider(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("sandbox provider must not be blank")
    return normalized


async def _conversation(
    session: AsyncSession,
    access: AuthContext,
    conversation_id: UUID,
    *,
    lock: bool = False,
) -> Conversation:
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == _tenant_id(access),
        Conversation.user_id == access.user_id,
        Conversation.status == "active",
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise DocumentNotFoundError(f"conversation not found: {conversation_id}")
    return row


async def _active_session(
    session: AsyncSession, access: AuthContext, session_id: UUID
) -> SandboxSession:
    row = await session.scalar(
        select(SandboxSession)
        .where(
            SandboxSession.id == session_id,
            SandboxSession.tenant_id == _tenant_id(access),
            SandboxSession.user_id == access.user_id,
            SandboxSession.status == "active",
            SandboxSession.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise DocumentNotFoundError("sandbox session not found")
    await _conversation(session, access, row.conversation_id)
    return row


def _state(row: SandboxSession) -> SandboxSessionState:
    provider_state = row.provider_state if isinstance(row.provider_state, dict) else {}
    return SandboxSessionState(
        id=row.id,
        provider=row.provider,
        status=row.status,  # type: ignore[arg-type]
        manifest=_manifest_resources(row.manifest),
        environment_id=_optional_identifier(provider_state.get("environment_id")),
        materialized_files=_provider_files(provider_state, "materialized_files"),
        observed_files=_provider_files(provider_state, "observed_files"),
    )


def _manifest_resources(value: object) -> tuple[SandboxManifestResource, ...]:
    payload = value if isinstance(value, dict) else {}
    raw_resources = payload.get("resources")
    if not isinstance(raw_resources, list):
        return ()
    resources: list[SandboxManifestResource] = []
    for item in raw_resources:
        if not isinstance(item, dict):
            continue
        try:
            resource = SandboxManifestResource(
                resource_id=_identifier(item.get("resource_id"), "resource"),
                name=_identifier(item.get("name"), "resource name"),
                mime_type=_identifier(item.get("mime_type"), "resource mime type"),
                size_bytes=_size(item.get("size_bytes")),
            )
        except ValueError:
            continue
        if not any(existing.resource_id == resource.resource_id for existing in resources):
            resources.append(resource)
    return tuple(resources)


def _provider_files(value: object, key: str) -> tuple[SandboxProviderFile, ...]:
    payload = value if isinstance(value, dict) else {}
    raw_files = payload.get(key)
    if not isinstance(raw_files, list):
        return ()
    files: list[SandboxProviderFile] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        try:
            file = SandboxProviderFile(
                id=_identifier(item.get("id"), "provider file"),
                name=_identifier(item.get("name"), "provider file name"),
                resource_id=_optional_identifier(item.get("resource_id")),
            )
        except ValueError:
            continue
        if not any(existing.id == file.id for existing in files):
            files.append(file)
    return tuple(files)


def _provider_state(
    current: object,
    *,
    environment_id: str | None = None,
    materialized_files: Iterable[SandboxProviderFile] | None = None,
    observed_files: Iterable[SandboxProviderFile] | None = None,
) -> dict[str, object]:
    previous = current if isinstance(current, dict) else {}
    state: dict[str, object] = {
        "materialized_files": [
            _file_payload(item)
            for item in (
                _unique_files(materialized_files)
                if materialized_files is not None
                else _provider_files(previous, "materialized_files")
            )
        ],
        "observed_files": [
            _file_payload(item)
            for item in (
                _unique_files(observed_files)
                if observed_files is not None
                else _provider_files(previous, "observed_files")
            )
        ],
    }
    selected_environment = (
        environment_id
        if environment_id is not None
        else _optional_identifier(previous.get("environment_id"))
    )
    if selected_environment is not None:
        state["environment_id"] = selected_environment
    return state


def _unique_files(files: Iterable[SandboxProviderFile]) -> tuple[SandboxProviderFile, ...]:
    result: list[SandboxProviderFile] = []
    seen: set[str] = set()
    for item in files:
        if item.id not in seen:
            seen.add(item.id)
            result.append(item)
    return tuple(result)


def _resource_payload(resource: SandboxManifestResource) -> dict[str, object]:
    return {
        "resource_id": resource.resource_id,
        "name": resource.name,
        "mime_type": resource.mime_type,
        "size_bytes": resource.size_bytes,
    }


def _file_payload(file: SandboxProviderFile) -> dict[str, object]:
    return {"id": file.id, "name": file.name, "resource_id": file.resource_id}


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be blank")
    return value.strip()


def _optional_identifier(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _size(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("resource size is invalid")
    return value


__all__ = ["SandboxSessionService"]
