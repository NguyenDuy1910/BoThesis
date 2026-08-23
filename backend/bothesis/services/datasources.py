"""Tenant datasource lifecycle and durable ingestion job orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from bothesis.connector.base import StaticCredentialsProvider
from bothesis.connector.confluence.connector import ConfluenceConnector
from bothesis.connector.file.file_connector import FileConnector
from bothesis.connector.file import DEFAULT_MAX_FILE_BYTES
from bothesis.connector.file.processing import FileProcessor
from bothesis.db.models import Connector, ConnectorScope, Item, SyncRun
from bothesis.connector.protocol import SourceProvider
from bothesis.document_index.raw_storage import DocumentStorage
from bothesis.services import (
    ACTIVE_STATUS,
    INACTIVE_STATUS,
    KNOWLEDGE_READ_PERMISSION,
    SOURCE_MANAGE_PERMISSION,
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    AuthorizationError,
    ConnectorCredentialService,
    ItemService,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)

SUPPORTED_PROVIDERS = frozenset({"confluence", SourceProvider.FILE.value})
CONNECTOR_STATUSES = frozenset({"draft", "active", "disabled", "error"})
SYNC_RUN_STATUSES = frozenset(
    {"pending", "running", "completed", "failed", "cancelled"}
)
_SECRET_KEY_TERMS = frozenset(
    {"access_key", "api_key", "authorization", "credential", "password", "secret", "token"}
)


class DatasourceService:
    """Manage configured connector connection instances and their scopes."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        credential_encryption_key: str | None = None,
        object_storage: DocumentStorage | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._credential_encryption_key = credential_encryption_key
        self._object_storage = object_storage
        self._audit = audit or AuditService(session)

    async def capabilities(self, actor: AuthContext) -> dict[str, Any]:
        require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return {
            "providers": [
                {
                    "provider": "confluence",
                    "label": "Confluence",
                    "credentials_required": True,
                    "scope_type": "space",
                },
                {
                    "provider": SourceProvider.FILE.value,
                    "label": "Files",
                    "credentials_required": False,
                    "scope_type": "source_provider",
                },
            ]
        }

    async def list_chat_connectors(
        self,
        actor: AuthContext,
        *,
        connector_ids: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        """Return active tenant connections that can back chat retrieval.

        Connector visibility requires tenant knowledge access. Content returned
        through any listed connection is still independently constrained by
        the user's indexed document ACLs during retrieval.
        """

        tenant_id = require_tenant_permission(actor, KNOWLEDGE_READ_PERMISSION)
        normalized_ids = (
            tuple(dict.fromkeys(connector_ids))
            if connector_ids is not None
            else None
        )
        if normalized_ids is not None and any(value < 1 for value in normalized_ids):
            raise AuthorizationError("one or more selected connectors are unavailable")
        filters = [
            Connector.tenant_id == tenant_id,
            Connector.status == ACTIVE_STATUS,
        ]
        if normalized_ids is not None:
            if not normalized_ids:
                return {"items": [], "total": 0}
            filters.append(Connector.id.in_(normalized_ids))
        connectors = list(
            await self._session.scalars(
                select(Connector)
                .options(selectinload(Connector.credential))
                .where(*filters)
                .order_by(Connector.display_name, Connector.id)
            )
        )
        if normalized_ids is not None and {
            connector.id for connector in connectors
        } != set(normalized_ids):
            raise AuthorizationError("one or more selected connectors are unavailable")
        return {
            "items": [
                {
                    "id": str(connector.id),
                    "provider": connector.provider,
                    "display_name": connector.display_name,
                    "status": connector.status,
                    "capabilities": ["knowledge_search"],
                }
                for connector in connectors
            ],
            "total": len(connectors),
        }

    async def list_datasources(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        provider: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            Connector.tenant_id == tenant_id,
            Connector.status != "deleted",
        ]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    Connector.display_name.ilike(term),
                    Connector.provider.ilike(term),
                )
            )
        if provider:
            filters.append(Connector.provider == provider.strip().casefold())
        if status:
            normalized_status = status.strip().casefold()
            if normalized_status not in CONNECTOR_STATUSES:
                raise AdminValidationError("unsupported datasource status")
            filters.append(Connector.status == normalized_status)

        total = await self._session.scalar(
            select(func.count()).select_from(
                select(Connector.id).where(*filters).subquery()
            )
        )
        connectors = list(
            await self._session.scalars(
                select(Connector)
                .options(selectinload(Connector.credential))
                .where(*filters)
                .order_by(Connector.display_name, Connector.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        scopes = await self._scopes_for([connector.id for connector in connectors])
        return {
            "items": [
                _connector_payload(connector, scopes.get(connector.id, []))
                for connector in connectors
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_datasource(
        self, actor: AuthContext, connector_id: int
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connector = await self._connector(tenant_id, connector_id)
        scopes = await self._scopes_for([connector.id])
        return _connector_payload(connector, scopes.get(connector.id, []))

    async def create_datasource(
        self,
        actor: AuthContext,
        *,
        provider: str,
        display_name: str,
        settings: Mapping[str, Any],
        credentials: Mapping[str, Any] | None = None,
        credential_type: str | None = None,
        owner_type: str = "tenant",
        scopes: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        normalized_provider = _provider(provider)
        normalized_name = normalize_required_text(
            display_name, "datasource display name", 255
        )
        normalized_settings = _settings(normalized_provider, settings)
        normalized_owner_type = _owner_type(owner_type)
        _validate_credentials(normalized_provider, credentials)
        duplicate = await self._session.scalar(
            select(Connector.id).where(
                Connector.tenant_id == tenant_id,
                Connector.display_name == normalized_name,
                Connector.status != "deleted",
            )
        )
        if duplicate is not None:
            raise AdminConflictError(
                f"datasource name already exists in tenant: {normalized_name}"
            )
        connector = Connector(
            tenant_id=tenant_id,
            owner_type=normalized_owner_type,
            owner_user_id=(
                actor.user_id if normalized_owner_type == "user" else None
            ),
            provider=normalized_provider,
            display_name=normalized_name,
            settings=normalized_settings,
            status="draft",
            created_by_user_id=actor.user_id,
        )
        self._session.add(connector)
        await self._session.flush()
        connector.settings = {
            **normalized_settings,
            "connector_id": str(connector.id),
        }
        normalized_settings = dict(connector.settings)
        if credentials is not None:
            await self._credentials().store(
                connector.id,
                credential_type=credential_type or normalized_provider,
                payload=credentials,
            )
        source_scopes = scopes or _default_scopes(
            normalized_provider, normalized_settings
        )
        await self._replace_scopes(connector, source_scopes)
        await self._audit.record(
            actor,
            action="datasource.created",
            resource_type="datasource",
            resource_id=str(connector.id),
            details={
                "provider": connector.provider,
                "display_name": connector.display_name,
            },
        )
        return await self.get_datasource(actor, connector.id)

    async def upload_file(
        self,
        actor: AuthContext,
        connector_id: int,
        *,
        file_name: str,
        content: AsyncIterable[bytes],
    ) -> dict[str, Any]:
        """Stream and store one validated tenant-scoped managed file."""

        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connector = await self._connector(tenant_id, connector_id)
        if connector.provider != SourceProvider.FILE.value:
            raise AdminValidationError("files can only be uploaded to a managed file connection")
        if self._object_storage is None:
            raise AdminExternalUnavailableError("object storage is required for file uploads")

        normalized_file_name = _upload_file_name(file_name)
        settings = dict(connector.settings)
        try:
            max_file_bytes = int(
                settings.get("max_file_bytes") or DEFAULT_MAX_FILE_BYTES
            )
        except (TypeError, ValueError) as exc:
            raise AdminValidationError(
                "managed file max_file_bytes must be a positive integer"
            ) from exc
        if max_file_bytes < 1:
            raise AdminValidationError(
                "managed file max_file_bytes must be a positive integer"
            )

        external_id = uuid4().hex
        temporary = NamedTemporaryFile(
            mode="wb",
            prefix=f".{external_id}-",
            suffix=Path(normalized_file_name).suffix.casefold(),
            delete=False,
        )
        temporary_path = Path(temporary.name)
        try:
            received_bytes = 0
            async for chunk in content:
                if not isinstance(chunk, bytes):
                    raise AdminValidationError(
                        "managed file upload chunks must be bytes"
                    )
                next_size = received_bytes + len(chunk)
                if next_size > max_file_bytes:
                    raise AdminValidationError(
                        f"File exceeds {max_file_bytes} byte limit: {next_size} bytes"
                    )
                if chunk:
                    await asyncio.to_thread(temporary.write, chunk)
                received_bytes = next_size
            await asyncio.to_thread(temporary.close)

            try:
                processor = await asyncio.to_thread(
                    FileProcessor,
                    max_file_bytes=max_file_bytes,
                )
                processed = await asyncio.to_thread(
                    processor.process_path,
                    temporary_path,
                    file_name=normalized_file_name,
                )
            except ValueError as exc:
                raise AdminValidationError(str(exc)) from exc

            storage_key = (
                f"tenants/{tenant_id}/connectors/{connector.id}/items/"
                f"{external_id}/{normalized_file_name}"
            )
            await asyncio.to_thread(
                self._object_storage.put_path,
                temporary_path,
                storage_key,
                content_type=processed.mime_type,
            )
        finally:
            if not temporary.closed:
                await asyncio.to_thread(temporary.close)
            await asyncio.to_thread(temporary_path.unlink, missing_ok=True)

        scope = await self._session.scalar(
            select(ConnectorScope).where(
                ConnectorScope.connector_id == connector.id,
                ConnectorScope.status != "deleted",
            )
        )
        if scope is None:
            raise AdminValidationError("managed file connection has no active scope")
        uploaded_at = datetime.now(UTC)
        item = await ItemService(self._session).upsert_external_item(
            scope.id,
            external_id,
            canonical_source_id=external_id,
            item_type="document",
            document_kind=_document_kind(processed.mime_type),
            title=normalized_file_name,
            mime_type=processed.mime_type,
            size_bytes=processed.size_bytes,
            storage_key=storage_key,
            content_sha256=processed.sha256,
            external_updated_at=uploaded_at,
            metadata={
                "source_kind": "file",
                "file_name": normalized_file_name,
                "uploaded_at": uploaded_at.isoformat(),
            },
            allowed_principal_tokens=[
                str(actor.user_id),
                f"email:{actor.email.casefold()}",
                *actor.principal_tokens,
            ],
            status="pending",
            require_active_scope=False,
        )
        await self._audit.record(
            actor,
            action="datasource.file_uploaded",
            resource_type="datasource",
            resource_id=str(connector.id),
            details={"mime_type": processed.mime_type, "size_bytes": processed.size_bytes},
        )
        return {
            "id": str(item.id),
            "external_id": external_id,
            "file_name": normalized_file_name,
            "mime_type": processed.mime_type,
            "size_bytes": processed.size_bytes,
        }

    async def update_datasource(
        self,
        actor: AuthContext,
        connector_id: int,
        *,
        display_name: str | None = None,
        settings: Mapping[str, Any] | None = None,
        credentials: Mapping[str, Any] | None = None,
        credential_type: str | None = None,
        status: str | None = None,
        scopes: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connector = await self._connector(tenant_id, connector_id)
        changed: list[str] = []
        configuration_changed = False
        if display_name is not None:
            normalized_name = normalize_required_text(
                display_name, "datasource display name", 255
            )
            duplicate = await self._session.scalar(
                select(Connector.id).where(
                    Connector.tenant_id == tenant_id,
                    Connector.display_name == normalized_name,
                    Connector.id != connector.id,
                    Connector.status != "deleted",
                )
            )
            if duplicate is not None:
                raise AdminConflictError(
                    f"datasource name already exists in tenant: {normalized_name}"
                )
            connector.display_name = normalized_name
            changed.append("display_name")
        if settings is not None:
            connector.settings = {
                **_settings(connector.provider, settings),
                "connector_id": str(connector.id),
            }
            changed.append("settings")
            configuration_changed = True
        if credentials is not None:
            _validate_credentials(connector.provider, credentials)
            await self._credentials().store(
                connector.id,
                credential_type=credential_type or connector.provider,
                payload=credentials,
            )
            changed.append("credentials")
            configuration_changed = True
        if scopes is not None:
            await self._replace_scopes(connector, scopes)
            changed.append("scopes")
            configuration_changed = True
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in CONNECTOR_STATUSES:
                raise AdminValidationError("unsupported datasource status")
            connector.status = normalized_status
            changed.append("status")
        elif configuration_changed:
            connector.status = "draft"
        await self._session.flush()
        await self._audit.record(
            actor,
            action="datasource.updated",
            resource_type="datasource",
            resource_id=str(connector.id),
            details={"changed_fields": changed},
        )
        return await self.get_datasource(actor, connector.id)

    async def validate_datasource(
        self, actor: AuthContext, connector_id: int
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connector = await self._connector(tenant_id, connector_id)
        try:
            if connector.provider == SourceProvider.FILE.value:
                runtime = FileConnector(dict(connector.settings))
                connected = await runtime.test_connection()
            elif connector.provider == "confluence":
                credentials = await self._credentials().resolve(connector.id)
                runtime = _confluence_runtime(connector, credentials)
                await asyncio.to_thread(runtime.validate_connector_settings)
                connected = True
            else:
                raise AdminValidationError("unsupported datasource provider")
        except AdminExternalUnavailableError:
            raise
        except (LookupError, ValueError) as exc:
            raise AdminExternalUnavailableError(str(exc)) from exc
        except Exception as exc:
            raise AdminExternalUnavailableError(
                f"{connector.provider} connection validation failed"
            ) from exc
        if not connected:
            raise AdminExternalUnavailableError(
                f"{connector.provider} connection validation failed"
            )
        connector.status = ACTIVE_STATUS
        await self._session.flush()
        await self._audit.record(
            actor,
            action="datasource.validated",
            resource_type="datasource",
            resource_id=str(connector.id),
            details={"provider": connector.provider},
        )
        return {
            "valid": True,
            "status": connector.status,
            "validated_at": timestamp(datetime.now(UTC)),
        }

    async def trigger_sync(
        self,
        actor: AuthContext,
        connector_id: int,
        *,
        scope_id: int | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connector = await self._connector(tenant_id, connector_id)
        if connector.status != ACTIVE_STATUS:
            raise AdminConflictError(
                "validate and activate the datasource before starting a sync"
            )
        statement = select(ConnectorScope).where(
            ConnectorScope.connector_id == connector.id,
            ConnectorScope.status == ACTIVE_STATUS,
        )
        if scope_id is not None:
            statement = statement.where(ConnectorScope.id == scope_id)
        scopes = list(
            await self._session.scalars(statement.with_for_update())
        )
        if not scopes:
            raise AdminNotFoundError("no active datasource scopes were found")
        runs: list[SyncRun] = []
        for scope in scopes:
            active_run = await self._session.scalar(
                select(SyncRun.id).where(
                    SyncRun.connector_scope_id == scope.id,
                    SyncRun.status.in_(("pending", "running")),
                )
            )
            if active_run is not None:
                raise AdminConflictError(
                    f"scope {scope.id} already has an active sync run"
                )
            run = SyncRun(
                connector_scope_id=scope.id,
                trigger_type="manual",
                status="pending",
            )
            self._session.add(run)
            runs.append(run)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="datasource.sync_requested",
            resource_type="datasource",
            resource_id=str(connector.id),
            details={"run_ids": [str(run.id) for run in runs]},
        )
        return {
            "items": [await self._sync_payload(run, connector, scope) for run, scope in zip(runs, scopes, strict=True)],
            "total": len(runs),
        }

    async def list_sync_runs(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        connector_id: int | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [Connector.tenant_id == tenant_id, Connector.status != "deleted"]
        if status:
            normalized_status = status.strip().casefold()
            if normalized_status not in SYNC_RUN_STATUSES:
                raise AdminValidationError("unsupported ingestion status")
            filters.append(SyncRun.status == normalized_status)
        if connector_id is not None:
            filters.append(Connector.id == connector_id)
        base = (
            select(SyncRun, ConnectorScope, Connector)
            .join(ConnectorScope, ConnectorScope.id == SyncRun.connector_scope_id)
            .join(Connector, Connector.id == ConnectorScope.connector_id)
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        rows = (
            await self._session.execute(
                base.order_by(SyncRun.created_at.desc(), SyncRun.id.desc())
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [
                await self._sync_payload(run, connector, scope)
                for run, scope, connector in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_sync_run(
        self, actor: AuthContext, run_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        row = (
            await self._session.execute(
                select(SyncRun, ConnectorScope, Connector)
                .join(ConnectorScope, ConnectorScope.id == SyncRun.connector_scope_id)
                .join(Connector, Connector.id == ConnectorScope.connector_id)
                .where(SyncRun.id == run_id, Connector.tenant_id == tenant_id)
            )
        ).one_or_none()
        if row is None:
            raise AdminNotFoundError(f"ingestion run not found: {run_id}")
        run, scope, connector = row
        return await self._sync_payload(run, connector, scope)

    async def retry_sync(self, actor: AuthContext, run_id: UUID) -> dict[str, Any]:
        previous = await self.get_sync_run(actor, run_id)
        if previous["status"] not in {"failed", "cancelled"}:
            raise AdminConflictError("only failed or cancelled runs can be retried")
        result = await self.trigger_sync(
            actor,
            int(previous["datasource"]["id"]),
            scope_id=int(previous["scope"]["id"]),
        )
        return result["items"][0]

    async def cancel_sync(self, actor: AuthContext, run_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        row = (
            await self._session.execute(
                select(SyncRun, ConnectorScope, Connector)
                .join(ConnectorScope, ConnectorScope.id == SyncRun.connector_scope_id)
                .join(Connector, Connector.id == ConnectorScope.connector_id)
                .where(SyncRun.id == run_id, Connector.tenant_id == tenant_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise AdminNotFoundError(f"ingestion run not found: {run_id}")
        run, scope, connector = row
        if run.status not in {"pending", "running"}:
            raise AdminConflictError("only pending or running syncs can be cancelled")
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="datasource.sync_cancelled",
            resource_type="sync_run",
            resource_id=str(run.id),
        )
        return await self._sync_payload(run, connector, scope)

    async def delete_datasource(self, actor: AuthContext, connector_id: int) -> None:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connector = await self._connector(tenant_id, connector_id)
        active_runs = await self._session.scalar(
            select(func.count())
            .select_from(SyncRun)
            .join(ConnectorScope, ConnectorScope.id == SyncRun.connector_scope_id)
            .where(
                ConnectorScope.connector_id == connector.id,
                SyncRun.status.in_(("pending", "running")),
            )
        )
        if active_runs:
            raise AdminConflictError(
                "cancel active ingestion runs before deleting this datasource"
            )
        connector.status = "deleted"
        scopes = list(
            await self._session.scalars(
                select(ConnectorScope).where(
                    ConnectorScope.connector_id == connector.id,
                    ConnectorScope.status != "deleted",
                )
            )
        )
        for scope in scopes:
            scope.status = "deleted"
        await self._session.flush()
        await self._audit.record(
            actor,
            action="datasource.deleted",
            resource_type="datasource",
            resource_id=str(connector.id),
        )

    async def _connector(self, tenant_id: UUID, connector_id: int) -> Connector:
        connector = await self._session.scalar(
            select(Connector).where(
                Connector.id == connector_id,
                Connector.tenant_id == tenant_id,
                Connector.status != "deleted",
            ).options(joinedload(Connector.credential))
        )
        if connector is None:
            raise AdminNotFoundError(f"datasource not found: {connector_id}")
        return connector

    def _credentials(self) -> ConnectorCredentialService:
        if not self._credential_encryption_key:
            raise AdminExternalUnavailableError(
                "BOTHESIS_CONNECTOR_ENCRYPTION_KEY is not configured"
            )
        return ConnectorCredentialService(
            self._session, self._credential_encryption_key
        )

    async def _replace_scopes(
        self, connector: Connector, scopes: list[Mapping[str, Any]]
    ) -> None:
        if not scopes:
            raise AdminValidationError("at least one datasource scope is required")
        normalized: dict[str, dict[str, Any]] = {}
        for raw_scope in scopes:
            scope_value = normalize_required_text(
                str(raw_scope.get("scope_value") or ""), "scope value", 2_000
            )
            if scope_value in normalized:
                raise AdminValidationError("scope values must be unique")
            normalized[scope_value] = {
                "display_name": normalize_required_text(
                    str(raw_scope.get("display_name") or scope_value),
                    "scope display name",
                    255,
                ),
                "scope_type": normalize_required_text(
                    str(raw_scope.get("scope_type") or "scope"),
                    "scope type",
                    32,
                ).casefold(),
                "settings": _non_secret_mapping(raw_scope.get("settings") or {}),
                "sync_schedule": _non_secret_mapping(
                    raw_scope.get("sync_schedule") or {}
                ),
            }
        existing = list(
            await self._session.scalars(
                select(ConnectorScope)
                .where(ConnectorScope.connector_id == connector.id)
                .with_for_update()
            )
        )
        by_value = {scope.scope_value: scope for scope in existing}
        for scope in existing:
            if scope.scope_value not in normalized:
                scope.status = "deleted"
        for scope_value, values in normalized.items():
            scope = by_value.get(scope_value)
            if scope is None:
                self._session.add(
                    ConnectorScope(
                        connector_id=connector.id,
                        scope_value=scope_value,
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(scope, key, value)
                scope.status = ACTIVE_STATUS
        await self._session.flush()

    async def _scopes_for(
        self, connector_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        if not connector_ids:
            return {}
        scopes = list(
            await self._session.scalars(
                select(ConnectorScope)
                .where(
                    ConnectorScope.connector_id.in_(connector_ids),
                    ConnectorScope.status != "deleted",
                )
                .order_by(ConnectorScope.display_name, ConnectorScope.id)
            )
        )
        scope_ids = [scope.id for scope in scopes]
        latest_by_scope: dict[int, SyncRun] = {}
        if scope_ids:
            latest_runs = list(
                await self._session.scalars(
                    select(SyncRun)
                    .where(SyncRun.connector_scope_id.in_(scope_ids))
                    .order_by(
                        SyncRun.connector_scope_id,
                        SyncRun.created_at.desc(),
                        SyncRun.id.desc(),
                    )
                    .distinct(SyncRun.connector_scope_id)
                )
            )
            latest_by_scope = {
                run.connector_scope_id: run for run in latest_runs
            }
        document_counts = dict(
            (
                await self._session.execute(
                    select(Item.connector_scope_id, func.count(Item.id))
                    .where(
                        Item.connector_scope_id.in_(scope_ids),
                        Item.status != "deleted",
                    )
                    .group_by(Item.connector_scope_id)
                )
            ).all()
        ) if scope_ids else {}
        result: dict[int, list[dict[str, Any]]] = {}
        for scope in scopes:
            latest = latest_by_scope.get(scope.id)
            result.setdefault(scope.connector_id, []).append(
                {
                    "id": str(scope.id),
                    "scope_value": scope.scope_value,
                    "display_name": scope.display_name,
                    "scope_type": scope.scope_type,
                    "status": scope.status,
                    "item_count": int(document_counts.get(scope.id, 0)),
                    "sync_schedule": dict(scope.sync_schedule),
                    "last_synced_at": timestamp(scope.last_synced_at),
                    "last_indexed_at": timestamp(scope.last_indexed_at),
                    "latest_run": (
                        {
                            "id": str(latest.id),
                            "status": latest.status,
                            "created_at": timestamp(latest.created_at),
                        }
                        if latest is not None
                        else None
                    ),
                }
            )
        return result

    async def _sync_payload(
        self, run: SyncRun, connector: Connector, scope: ConnectorScope
    ) -> dict[str, Any]:
        return {
            "id": str(run.id),
            "trigger_type": run.trigger_type,
            "status": run.status,
            "discovered_item_count": run.discovered_item_count,
            "processed_item_count": run.processed_item_count,
            "written_chunk_count": run.written_chunk_count,
            "deleted_item_count": run.deleted_item_count,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "started_at": timestamp(run.started_at),
            "finished_at": timestamp(run.finished_at),
            "created_at": timestamp(run.created_at),
            "datasource": {
                "id": str(connector.id),
                "display_name": connector.display_name,
                "provider": connector.provider,
            },
            "scope": {
                "id": str(scope.id),
                "display_name": scope.display_name,
                "scope_value": scope.scope_value,
            },
        }


def _provider(value: str) -> str:
    normalized = normalize_required_text(value, "datasource provider", 32).casefold()
    if normalized not in SUPPORTED_PROVIDERS:
        raise AdminValidationError(
            "unsupported datasource provider; supported providers are confluence and file"
        )
    return normalized


def _settings(provider: str, value: Mapping[str, Any]) -> dict[str, Any]:
    settings = _non_secret_mapping(value)
    if provider == "confluence":
        wiki_base = settings.get("wiki_base")
        if not isinstance(wiki_base, str) or not wiki_base.strip():
            raise AdminValidationError("Confluence wiki_base is required")
        is_cloud = settings.get("is_cloud", True)
        if not isinstance(is_cloud, bool):
            raise AdminValidationError("Confluence is_cloud must be a boolean")
    return settings


def _non_secret_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdminValidationError("settings must be a JSON object")
    result = dict(value)
    for key, nested in result.items():
        normalized_key = str(key).casefold()
        if any(term in normalized_key for term in _SECRET_KEY_TERMS):
            raise AdminValidationError(
                "secret values must use the credentials object, not datasource settings"
            )
        if isinstance(nested, Mapping):
            _non_secret_mapping(nested)
    return result


def _validate_credentials(
    provider: str, value: Mapping[str, Any] | None
) -> None:
    if provider == "confluence" and not value:
        raise AdminValidationError("Confluence credentials are required")
    if value is not None and not isinstance(value, Mapping):
        raise AdminValidationError("credentials must be a JSON object")


def _owner_type(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in {"user", "tenant"}:
        raise AdminValidationError("connector owner_type must be user or tenant")
    return normalized


def _default_scopes(
    provider: str, settings: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    if provider == SourceProvider.FILE.value:
        return [
            {
                "scope_value": SourceProvider.FILE.value,
                "display_name": "Files",
                "scope_type": "source_provider",
            }
        ]
    space = str(settings.get("space") or "all").strip()
    return [
        {
            "scope_value": space,
            "display_name": space if space != "all" else "All spaces",
            "scope_type": "space",
        }
    ]


def _confluence_runtime(
    connector: Connector, credentials: Mapping[str, Any]
) -> ConfluenceConnector:
    settings = connector.settings
    runtime = ConfluenceConnector(
        str(settings["wiki_base"]),
        is_cloud=bool(settings.get("is_cloud", True)),
        space=str(settings.get("space") or ""),
        page_id=str(settings.get("page_id") or ""),
        index_recursively=bool(settings.get("index_recursively", False)),
        cql_query=(str(settings["cql_query"]) if settings.get("cql_query") else None),
        batch_size=int(settings.get("batch_size") or 50),
        labels_to_skip=[str(value) for value in settings.get("labels_to_skip") or []],
        timezone_offset=float(settings.get("timezone_offset") or 0),
    )
    runtime.set_credentials_provider(
        StaticCredentialsProvider(
            tenant_id=str(connector.tenant_id),
            provider_key=str(connector.id),
            credentials=dict(credentials),
        )
    )
    return runtime


def _upload_file_name(value: str) -> str:
    normalized = normalize_required_text(value, "file name", 240)
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized or "\x00" in normalized:
        raise AdminValidationError("file name is invalid")
    return normalized


def _document_kind(mime_type: str) -> str:
    normalized = mime_type.casefold()
    if normalized == "application/pdf":
        return "pdf"
    if normalized.startswith("image/"):
        return "image"
    return "document"


def _connector_payload(
    connector: Connector, scopes: list[dict[str, Any]]
) -> dict[str, Any]:
    latest_synced_at = max(
        (scope["last_synced_at"] for scope in scopes if scope["last_synced_at"]),
        default=None,
    )
    return {
        "id": str(connector.id),
        "tenant_id": str(connector.tenant_id),
        "provider": connector.provider,
        "display_name": connector.display_name,
        "settings": dict(connector.settings),
        "credential_configured": connector.credential is not None,
        "owner_type": connector.owner_type,
        "owner_user_id": (
            str(connector.owner_user_id) if connector.owner_user_id else None
        ),
        "status": connector.status,
        "scope_count": len(scopes),
        "item_count": sum(scope["item_count"] for scope in scopes),
        "last_synced_at": latest_synced_at,
        "scopes": scopes,
        "created_by_user_id": (
            str(connector.created_by_user_id)
            if connector.created_by_user_id is not None
            else None
        ),
        "created_at": timestamp(connector.created_at),
        "updated_at": timestamp(connector.updated_at),
    }


__all__ = ["DatasourceService"]
