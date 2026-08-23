"""Tenant Item inventory and governed lifecycle administration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Connector, ConnectorScope, Item
from bothesis.document_index.vector_store import VectorStore
from bothesis.services import (
    ITEM_MANAGE_PERMISSION,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    DatasourceService,
    ItemService,
    normalize_page,
    require_tenant_permission,
    timestamp,
)

_ITEM_STATUSES = frozenset(
    {"pending", "processing", "ready", "failed", "unsupported"}
)


class AdminItemService:
    """Query tenant Items and apply explicit lifecycle transitions."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        vector_store: VectorStore | None = None,
        credential_encryption_key: str | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._vector_store = vector_store
        self._credential_encryption_key = credential_encryption_key
        self._audit = audit or AuditService(session)

    async def list_items(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
        item_type: str | None = None,
        connector_id: int | None = None,
        sort: str = "updated_at",
        direction: str = "desc",
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ITEM_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            Item.tenant_id == tenant_id,
            Item.status != "deleted",
            Item.deleted_at.is_(None),
        ]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(or_(Item.title.ilike(term), Item.external_id.ilike(term)))
        if status:
            normalized = status.strip().casefold()
            if normalized not in _ITEM_STATUSES:
                raise AdminValidationError("unsupported item status")
            filters.append(Item.status == normalized)
        if item_type:
            normalized_type = item_type.strip().casefold()
            if normalized_type not in {"collection", "document", "file"}:
                raise AdminValidationError("unsupported item type")
            filters.append(Item.item_type == normalized_type)
        if connector_id is not None:
            filters.append(Item.connector_id == connector_id)

        base = (
            select(Item, ConnectorScope, Connector)
            .outerjoin(ConnectorScope, ConnectorScope.id == Item.connector_scope_id)
            .outerjoin(Connector, Connector.id == Item.connector_id)
            .where(*filters)
        )
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        sort_columns = {
            "created_at": Item.created_at,
            "status": Item.status,
            "title": Item.title,
            "updated_at": Item.updated_at,
        }
        sort_column = sort_columns.get(sort)
        if sort_column is None or direction not in {"asc", "desc"}:
            raise AdminValidationError("unsupported item sort")
        order = sort_column.desc() if direction == "desc" else sort_column.asc()
        rows = (
            await self._session.execute(
                base.order_by(order, Item.id).limit(page_size).offset(offset)
            )
        ).all()
        return {
            "items": [_item_payload(item, scope, connector) for item, scope, connector in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_item(self, actor: AuthContext, item_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ITEM_MANAGE_PERMISSION)
        row = (
            await self._session.execute(
                select(Item, ConnectorScope, Connector)
                .outerjoin(ConnectorScope, ConnectorScope.id == Item.connector_scope_id)
                .outerjoin(Connector, Connector.id == Item.connector_id)
                .where(
                    Item.id == item_id,
                    Item.tenant_id == tenant_id,
                    Item.status != "deleted",
                    Item.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise AdminNotFoundError(f"item not found: {item_id}")
        item, scope, connector = row
        return {
            **_item_payload(item, scope, connector),
            "metadata": dict(item.metadata_),
            "allowed_principal_tokens": sorted(item.allowed_principal_tokens),
            "denied_principal_tokens": sorted(item.denied_principal_tokens),
            "raw_content_available": bool(item.storage_key),
        }

    async def update_status(
        self, actor: AuthContext, item_id: UUID, *, status: str
    ) -> dict[str, Any]:
        previous = await self.get_item(actor, item_id)
        normalized = status.strip().casefold()
        if normalized not in _ITEM_STATUSES:
            raise AdminValidationError("unsupported item status")
        item = await self._session.get(Item, item_id)
        assert item is not None
        item.status = normalized
        await self._session.flush()
        await self._audit.record(
            actor,
            action="item.status_updated",
            resource_type="item",
            resource_id=str(item.id),
            details={"previous_status": previous["status"], "status": normalized},
        )
        return await self.get_item(actor, item_id)

    async def retry_item(self, actor: AuthContext, item_id: UUID) -> dict[str, Any]:
        payload = await self.get_item(actor, item_id)
        if payload["status"] != "failed":
            raise AdminConflictError("only failed items can be retried")
        item = await self._session.get(Item, item_id)
        assert item is not None
        if item.connector_scope_id is None:
            item.status = "pending"
            await self._audit.record(
                actor,
                action="item.retry_requested",
                resource_type="item",
                resource_id=str(item.id),
                details={"mode": "index"},
            )
            return {"item": await self.get_item(actor, item.id), "ingestion_run": None}
        scope = await self._session.get(ConnectorScope, item.connector_scope_id)
        if scope is None:
            raise AdminConflictError("item connector scope is unavailable")
        sync_result = await DatasourceService(
            self._session,
            audit=self._audit,
            credential_encryption_key=self._credential_encryption_key,
        ).trigger_sync(actor, scope.connector_id, scope_id=scope.id)
        return {"item": payload, "ingestion_run": sync_result["items"][0]}

    async def delete_item(self, actor: AuthContext, item_id: UUID) -> None:
        require_tenant_permission(actor, ITEM_MANAGE_PERMISSION)
        await self.get_item(actor, item_id)
        if self._vector_store is None:
            raise RuntimeError("Qdrant is required to delete an indexed Item")
        await self._vector_store.soft_delete_document_points(str(item_id))
        await ItemService(self._session).soft_delete_item(item_id, actor=actor)
        await self._audit.record(
            actor,
            action="item.deleted",
            resource_type="item",
            resource_id=str(item_id),
        )


def _item_payload(
    item: Item,
    scope: ConnectorScope | None,
    connector: Connector | None,
) -> dict[str, Any]:
    processing = item.metadata_.get("processing")
    return {
        "id": str(item.id),
        "item_type": item.item_type,
        "document_kind": item.document_kind,
        "collection_kind": item.collection_kind,
        "title": item.title,
        "mime_type": item.mime_type,
        "size_bytes": item.size_bytes,
        "source_url": item.source_url,
        "external_id": item.external_id,
        "external_version": item.external_version,
        "parent_item_id": str(item.parent_item_id) if item.parent_item_id else None,
        "status": item.status,
        "indexed": isinstance(processing, dict)
        and processing.get("index_schema_version") is not None,
        "created_at": timestamp(item.created_at),
        "updated_at": timestamp(item.updated_at),
        "datasource": (
            {
                "id": str(connector.id),
                "display_name": connector.display_name,
                "provider": connector.provider,
            }
            if connector is not None
            else None
        ),
        "scope": (
            {
                "id": str(scope.id),
                "display_name": scope.display_name,
                "scope_value": scope.scope_value,
            }
            if scope is not None
            else None
        ),
    }


__all__ = ["AdminItemService"]
