"""The Source resource: one external resource synchronized into one Collection.

A Source is always built on a Connection and never carries a credential of its
own. Adding a second space from an account that is already connected creates a
Source and nothing else — no second authorization, no second secret.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bothesis.connector.registry import ConnectorRegistry
from bothesis.db.models import IngestionSource, IntegrationConnection, Item
from bothesis.integrations.registry import ConnectionProviderRegistry
from bothesis.services.audit import AuditService
from bothesis.services.integration_connections import IntegrationConnectionService
from bothesis.services import (
    CONNECTION_NEEDS_AUTHORIZATION,
    SOURCE_CONNECTION_REQUIRED,
    SOURCE_DISABLED,
    SOURCE_FAILED,
    SOURCE_PAUSED,
    SOURCE_READY,
    SOURCE_STATUSES,
    ControlPlaneConflictError,
    ControlPlaneNotFoundError,
    ControlPlaneValidationError,
    AuthContext,
    AuthorizationError,
    normalize_page,
    normalize_required_text,
    timestamp,
)

#: Statuses an operator may set directly. The rest are consequences of the
#: connection's own state and are never typed in by hand.
_ASSIGNABLE_STATUSES = (SOURCE_READY, SOURCE_PAUSED, SOURCE_DISABLED)
_SYNC_MODES = ("manual", "scheduled")


class IngestionSourceService:
    """Manage independently checkpointed sources attached to Connections."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        providers: ConnectionProviderRegistry | None = None,
        registry: ConnectorRegistry | None = None,
        credential_encryption_key: str | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)
        self._connections = IntegrationConnectionService(
            session,
            providers=providers,
            registry=registry,
            credential_encryption_key=credential_encryption_key,
            audit=self._audit,
        )

    async def create_source(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        *,
        target_item_id: UUID,
        display_name: str | None,
        config: Mapping[str, Any] | None = None,
        resource_type: str | None = None,
        external_resource_id: str | None = None,
        sync_mode: str = "manual",
    ) -> dict[str, Any]:
        """Point a connection at one destination Collection.

        A selected resource is enough on its own: the provider turns it into
        the config its connector runs on, so a caller never has to know that a
        Confluence space is a ``space`` key and a Shared Drive is a
        ``shared_drive_id``.
        """

        connection = await self._connections.connection_for_authorization(
            actor, integration_connection_id
        )
        target = await self._session.scalar(
            select(Item).where(
                Item.id == target_item_id,
                Item.tenant_id == connection.tenant_id,
                Item.item_type == "collection",
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if target is None:
            raise ControlPlaneNotFoundError(f"target Collection not found: {target_item_id}")
        normalized_resource = (
            normalize_required_text(external_resource_id, "resource id", 1_024)
            if external_resource_id is not None
            else None
        )
        if normalized_resource is not None:
            await self._reject_duplicate_resource(
                connection.id, resource_type, normalized_resource
            )
        resolved_config = dict(config or {})
        if normalized_resource is not None and resource_type is not None:
            resolved_config = {
                **await self._connections.resource_source_config(
                    connection,
                    resource_type=resource_type,
                    external_resource_id=normalized_resource,
                ),
                **resolved_config,
            }
        source = IngestionSource(
            integration_connection_id=connection.id,
            target_item_id=target.id,
            display_name=(
                normalize_required_text(display_name, "source display name", 255)
                if display_name is not None
                else None
            ),
            resource_type=resource_type,
            external_resource_id=normalized_resource,
            config=IntegrationConnectionService.non_secret_config(resolved_config),
            checkpoint={},
            sync_mode=_valid_sync_mode(sync_mode),
            # A source whose connection already needs attention says so from
            # the start rather than failing on its first run.
            status=(
                SOURCE_CONNECTION_REQUIRED
                if connection.status in CONNECTION_NEEDS_AUTHORIZATION
                else SOURCE_READY
            ),
            created_by_user_id=actor.user_id,
        )
        self._session.add(source)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="ingestion.source.created",
            resource_type="ingestion_source",
            resource_id=str(source.id),
            details={
                "integration_connection_id": str(connection.id),
                "target_item_id": str(target.id),
                "external_resource_id": normalized_resource,
            },
        )
        return await self.get_source(actor, source.id)

    async def list_sources(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        integration_connection_id: UUID | None = None,
        target_item_id: UUID | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = _require_tenant(actor)
        page, page_size, offset = normalize_page(page, page_size)
        filters: list[Any] = [
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.deleted_at.is_(None),
            IngestionSource.deleted_at.is_(None),
            self._connections.visibility(actor),
        ]
        if integration_connection_id is not None:
            filters.append(
                IngestionSource.integration_connection_id == integration_connection_id
            )
        if target_item_id is not None:
            filters.append(IngestionSource.target_item_id == target_item_id)
        if status is not None:
            filters.append(IngestionSource.status == _valid_status(status))
        query = (
            select(IngestionSource)
            .join(
                IntegrationConnection,
                IntegrationConnection.id == IngestionSource.integration_connection_id,
            )
            .options(
                joinedload(IngestionSource.integration_connection),
                joinedload(IngestionSource.target_item),
            )
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(
                query.with_only_columns(IngestionSource.id).subquery()
            )
        )
        sources = list(
            await self._session.scalars(
                query.order_by(IngestionSource.created_at.desc(), IngestionSource.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        return {
            "items": [self._source_payload(value) for value in sources],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_source(self, actor: AuthContext, source_id: UUID) -> dict[str, Any]:
        return self._source_payload(await self._source(actor, source_id))

    async def update_source(
        self,
        actor: AuthContext,
        source_id: UUID,
        *,
        display_name: str | None = None,
        config: Mapping[str, Any] | None = None,
        status: str | None = None,
        sync_mode: str | None = None,
    ) -> dict[str, Any]:
        source = await self._source(actor, source_id, for_update=True)
        if display_name is not None:
            source.display_name = normalize_required_text(
                display_name, "source display name", 255
            )
        if config is not None:
            source.config = IntegrationConnectionService.non_secret_config(config)
            # A different scope makes every stored cursor meaningless, so the
            # next run rediscovers from the beginning instead of skipping.
            source.checkpoint = {}
        if sync_mode is not None:
            source.sync_mode = _valid_sync_mode(sync_mode)
        if status is not None:
            normalized = _valid_status(status)
            if normalized not in _ASSIGNABLE_STATUSES:
                raise ControlPlaneValidationError(
                    f"{normalized} is set by the connection, not by an operator"
                )
            if source.status == SOURCE_CONNECTION_REQUIRED:
                raise ControlPlaneValidationError(
                    "this source is waiting on its connection; reconnect the account first"
                )
            source.status = normalized
            source.status_detail = None
        await self._session.flush()
        await self._audit.record(
            actor,
            action="ingestion.source.updated",
            resource_type="ingestion_source",
            resource_id=str(source.id),
        )
        return await self.get_source(actor, source.id)

    async def delete_source(self, actor: AuthContext, source_id: UUID) -> None:
        source = await self._source(actor, source_id, for_update=True)
        source.status = SOURCE_DISABLED
        source.deleted_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="ingestion.source.deleted",
            resource_type="ingestion_source",
            resource_id=str(source.id),
        )

    async def record_failure(self, source_id: UUID, detail: str) -> None:
        """Record why a source stopped producing, without touching its data."""

        source = await self._session.scalar(
            select(IngestionSource).where(IngestionSource.id == source_id)
        )
        if source is None or source.deleted_at is not None:
            return
        source.status = SOURCE_FAILED
        source.status_detail = detail[:1_000]
        await self._session.flush()

    async def runtime_for_source(self, source_id: UUID) -> tuple[IngestionSource, Any]:
        """Resolve one runnable source for the ingestion worker.

        This path is reached from a workflow, not from a request, so it checks
        durable state rather than a caller's permissions: the decision to run
        this source was already governed when it was created and scheduled.
        """

        source = await self._session.scalar(
            select(IngestionSource)
            .options(
                joinedload(IngestionSource.integration_connection),
                joinedload(IngestionSource.target_item),
            )
            .where(IngestionSource.id == source_id)
        )
        if (
            source is None
            or source.deleted_at is not None
            or source.status not in {SOURCE_READY, SOURCE_FAILED}
            or source.integration_connection.deleted_at is not None
        ):
            raise ControlPlaneNotFoundError(f"runnable ingestion source not found: {source_id}")
        runtime = await self._connections.runtime_for(
            source.integration_connection,
            source_config=source.config,
        )
        return source, runtime

    # -- Internals ----------------------------------------------------------

    async def _reject_duplicate_resource(
        self,
        integration_connection_id: UUID,
        resource_type: str | None,
        external_resource_id: str,
    ) -> None:
        duplicate = await self._session.scalar(
            select(IngestionSource.id).where(
                IngestionSource.integration_connection_id == integration_connection_id,
                IngestionSource.resource_type == resource_type,
                IngestionSource.external_resource_id == external_resource_id,
                IngestionSource.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise ControlPlaneConflictError(
                "this resource is already synchronized from this connection"
            )

    async def _source(
        self, actor: AuthContext, source_id: UUID, *, for_update: bool = False
    ) -> IngestionSource:
        tenant_id = _require_tenant(actor)
        statement = (
            select(IngestionSource)
            .options(
                joinedload(IngestionSource.integration_connection),
                joinedload(IngestionSource.target_item),
            )
            .join(
                IntegrationConnection,
                IntegrationConnection.id == IngestionSource.integration_connection_id,
            )
            .where(
                IngestionSource.id == source_id,
                IngestionSource.deleted_at.is_(None),
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.deleted_at.is_(None),
                self._connections.visibility(actor),
            )
        )
        if for_update:
            statement = statement.with_for_update(of=IngestionSource)
        source = await self._session.scalar(statement)
        if source is None:
            raise ControlPlaneNotFoundError(f"ingestion source not found: {source_id}")
        return source

    @staticmethod
    def _source_payload(source: IngestionSource) -> dict[str, Any]:
        connection = source.integration_connection
        return {
            "id": str(source.id),
            "integration_connection_id": str(source.integration_connection_id),
            "target_item_id": str(source.target_item_id),
            "display_name": source.display_name,
            "resource_type": source.resource_type,
            "external_resource_id": source.external_resource_id,
            "config": dict(source.config),
            "checkpoint": dict(source.checkpoint),
            "sync_mode": source.sync_mode,
            "status": source.status,
            "status_detail": source.status_detail,
            "last_ingested_at": timestamp(source.last_ingested_at),
            "last_indexed_at": timestamp(source.last_indexed_at),
            "integration_connection": {
                "id": str(connection.id),
                "display_name": connection.display_name,
                "connector_key": connection.connector_key,
                "status": connection.status,
                "owner_type": connection.owner_type,
                "account_label": connection.provider_account_label,
            },
            "schedule": None,
        }


def _require_tenant(actor: AuthContext) -> UUID:
    if actor.tenant_id is None:
        raise AuthorizationError("an active workspace membership is required")
    return actor.tenant_id


def _valid_status(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in SOURCE_STATUSES:
        raise ControlPlaneValidationError("unsupported Ingestion Source status")
    return normalized


def _valid_sync_mode(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in _SYNC_MODES:
        raise ControlPlaneValidationError("sync_mode must be manual or scheduled")
    return normalized


__all__ = ["IngestionSourceService"]
