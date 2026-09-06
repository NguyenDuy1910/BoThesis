"""Administration and runtime resolution of checkpointed Ingestion Sources."""

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
from bothesis.services.audit import AuditService
from bothesis.services.integration_connections import IntegrationConnectionService
from bothesis.services import (
    ACTIVE_STATUS,
    SOURCE_MANAGE_PERMISSION,
    AdminNotFoundError,
    AdminValidationError,
    AuthContext,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)


class IngestionSourceService:
    """Manage independently checkpointed sources attached to Connections."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: ConnectorRegistry | None = None,
        credential_encryption_key: str | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)
        self._connections = IntegrationConnectionService(
            session,
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
        config: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, integration_connection_id)
        target = await self._session.scalar(
            select(Item).where(
                Item.id == target_item_id,
                Item.tenant_id == tenant_id,
                Item.item_type == "collection",
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if target is None:
            raise AdminNotFoundError(f"target Collection not found: {target_item_id}")
        source = IngestionSource(
            integration_connection_id=connection.id,
            target_item_id=target.id,
            display_name=(
                normalize_required_text(display_name, "source display name", 255)
                if display_name is not None
                else None
            ),
            config=IntegrationConnectionService.non_secret_config(config),
            checkpoint={},
            status=ACTIVE_STATUS,
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
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.deleted_at.is_(None),
            IngestionSource.deleted_at.is_(None),
        ]
        if integration_connection_id is not None:
            filters.append(
                IngestionSource.integration_connection_id == integration_connection_id
            )
        if target_item_id is not None:
            filters.append(IngestionSource.target_item_id == target_item_id)
        if status is not None:
            filters.append(IngestionSource.status == status.strip().casefold())
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
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return self._source_payload(await self._source(tenant_id, source_id))

    async def update_source(
        self,
        actor: AuthContext,
        source_id: UUID,
        *,
        display_name: str | None = None,
        config: Mapping[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        source = await self._source(tenant_id, source_id, for_update=True)
        if display_name is not None:
            source.display_name = normalize_required_text(
                display_name, "source display name", 255
            )
        if config is not None:
            source.config = IntegrationConnectionService.non_secret_config(config)
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in {"active", "disabled", "error"}:
                raise AdminValidationError("unsupported Ingestion Source status")
            source.status = normalized_status
        await self._session.flush()
        await self._audit.record(
            actor,
            action="ingestion.source.updated",
            resource_type="ingestion_source",
            resource_id=str(source.id),
        )
        return await self.get_source(actor, source.id)

    async def delete_source(self, actor: AuthContext, source_id: UUID) -> None:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        source = await self._source(tenant_id, source_id, for_update=True)
        source.status = "disabled"
        source.deleted_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="ingestion.source.deleted",
            resource_type="ingestion_source",
            resource_id=str(source.id),
        )

    async def runtime_for_source(self, source_id: UUID) -> tuple[IngestionSource, Any]:
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
            or source.status != ACTIVE_STATUS
            or source.deleted_at is not None
            or source.integration_connection.status != ACTIVE_STATUS
            or source.integration_connection.deleted_at is not None
        ):
            raise AdminNotFoundError(f"active ingestion source not found: {source_id}")
        runtime = await self._connections.runtime_for(
            source.integration_connection,
            source_config=source.config,
        )
        return source, runtime

    async def _connection(
        self, tenant_id: UUID, integration_connection_id: UUID
    ) -> IntegrationConnection:
        connection = await self._session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == integration_connection_id,
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.deleted_at.is_(None),
            )
        )
        if connection is None:
            raise AdminNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        return connection

    async def _source(
        self, tenant_id: UUID, source_id: UUID, *, for_update: bool = False
    ) -> IngestionSource:
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
            )
        )
        if for_update:
            statement = statement.with_for_update(of=IngestionSource)
        source = await self._session.scalar(statement)
        if source is None:
            raise AdminNotFoundError(f"ingestion source not found: {source_id}")
        return source

    @staticmethod
    def _source_payload(source: IngestionSource) -> dict[str, Any]:
        return {
            "id": str(source.id),
            "integration_connection_id": str(source.integration_connection_id),
            "target_item_id": str(source.target_item_id),
            "display_name": source.display_name,
            "config": dict(source.config),
            "checkpoint": dict(source.checkpoint),
            "status": source.status,
            "last_ingested_at": timestamp(source.last_ingested_at),
            "last_indexed_at": timestamp(source.last_indexed_at),
            "integration_connection": {
                "id": str(source.integration_connection.id),
                "display_name": source.integration_connection.display_name,
                "connector_key": source.integration_connection.connector_key,
            },
            "schedule": None,
        }


__all__ = ["IngestionSourceService"]
