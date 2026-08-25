"""Tenant Item inventory and governed lifecycle administration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bothesis.db.models import Item, ItemOrigin, PluginBinding
from bothesis.document_index.vector_store import VectorStore
from bothesis.services import (
    ITEM_MANAGE_PERMISSION,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    CollectionAccessService,
    ItemService,
    PluginService,
    normalize_required_text,
    normalize_page,
    require_tenant_permission,
    timestamp,
)

_ITEM_STATUSES = {"pending", "processing", "ready", "failed", "unsupported"}


class AdminItemService:
    """Query canonical Items without coupling them to their Plugin Origins."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        vector_store: VectorStore | None = None,
        plugin_encryption_key: str | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._vector_store = vector_store
        self._plugin_encryption_key = plugin_encryption_key
        self._audit = audit or AuditService(session)

    async def create_collection(
        self,
        actor: AuthContext,
        *,
        title: str,
        parent_item_id: UUID | None = None,
        inherit_access: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ITEM_MANAGE_PERMISSION)
        item = await ItemService(self._session).create_collection(
            tenant_id=tenant_id,
            title=normalize_required_text(title, "collection title", 255),
            created_by_user_id=actor.user_id,
            parent_item_id=parent_item_id,
            inherit_access=inherit_access,
            metadata=metadata,
        )
        await CollectionAccessService(self._session).grant(
            item.id,
            principal_type="user",
            principal_id=actor.user_id,
            role="owner",
            actor=actor,
        )
        await self._audit.record(
            actor,
            action="collection.created",
            resource_type="collection",
            resource_id=str(item.id),
            details={
                "parent_item_id": str(parent_item_id) if parent_item_id else None,
                "creator_role": "owner",
            },
        )
        return await self.get_item(actor, item.id)

    async def list_items(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
        item_type: str | None = None,
        binding_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
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
            matching_origins = select(ItemOrigin.item_id).where(
                ItemOrigin.external_id.ilike(term), ItemOrigin.deleted_at.is_(None)
            )
            filters.append(
                or_(
                    Item.title.ilike(term),
                    cast(Item.metadata_["description"], String).ilike(term),
                    Item.id.in_(matching_origins),
                )
            )
        if status:
            normalized = status.strip().casefold()
            if normalized not in _ITEM_STATUSES:
                raise AdminValidationError("unsupported item status")
            filters.append(Item.status == normalized)
        if item_type:
            normalized_type = item_type.strip().casefold()
            if normalized_type not in {"collection", "document"}:
                raise AdminValidationError("unsupported item type")
            filters.append(Item.item_type == normalized_type)
        if binding_id is not None:
            filters.append(
                Item.id.in_(
                    select(ItemOrigin.item_id).where(
                        ItemOrigin.binding_id == binding_id,
                        ItemOrigin.deleted_at.is_(None),
                    )
                )
            )
        if created_by_user_id is not None:
            filters.append(Item.created_by_user_id == created_by_user_id)
        total = await self._session.scalar(
            select(func.count()).select_from(select(Item.id).where(*filters).subquery())
        )
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
        items = list(
            await self._session.scalars(
                select(Item)
                .options(
                    selectinload(Item.origins)
                    .selectinload(ItemOrigin.binding)
                    .selectinload(PluginBinding.connection)
                )
                .where(*filters)
                .order_by(order, Item.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        collection_ids = [item.id for item in items if item.item_type == "collection"]
        item_counts: dict[UUID, int] = {}
        source_counts: dict[UUID, int] = {}
        if collection_ids:
            item_counts = {
                parent_id: int(count)
                for parent_id, count in (
                    await self._session.execute(
                        select(Item.parent_item_id, func.count(Item.id))
                        .where(
                            Item.parent_item_id.in_(collection_ids),
                            Item.item_type == "document",
                            Item.status != "deleted",
                            Item.deleted_at.is_(None),
                        )
                        .group_by(Item.parent_item_id)
                    )
                ).all()
                if parent_id is not None
            }
            source_counts = {
                target_id: int(count)
                for target_id, count in (
                    await self._session.execute(
                        select(PluginBinding.target_item_id, func.count(PluginBinding.id))
                        .where(
                            PluginBinding.target_item_id.in_(collection_ids),
                            PluginBinding.deleted_at.is_(None),
                        )
                        .group_by(PluginBinding.target_item_id)
                    )
                ).all()
            }
        return {
            "items": [
                {
                    **self._payload(item),
                    **(
                        {
                            "item_count": item_counts.get(item.id, 0),
                            "source_count": source_counts.get(item.id, 0),
                        }
                        if item.item_type == "collection"
                        else {}
                    ),
                }
                for item in items
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_item(self, actor: AuthContext, item_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ITEM_MANAGE_PERMISSION)
        item = await self._session.scalar(
            select(Item)
            .options(
                selectinload(Item.origins)
                .selectinload(ItemOrigin.binding)
                .selectinload(PluginBinding.connection),
                selectinload(Item.access_grants),
            )
            .where(
                Item.id == item_id,
                Item.tenant_id == tenant_id,
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if item is None:
            raise AdminNotFoundError(f"item not found: {item_id}")
        return {
            **self._payload(item),
            "metadata": dict(item.metadata_),
            "inherit_access": item.inherit_access,
            "collection_access": [
                {
                    "principal_type": grant.principal_type,
                    "principal_id": str(grant.principal_id),
                    "role": grant.role,
                }
                for grant in item.access_grants
                if grant.deleted_at is None
            ],
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
            action=f"{item.item_type}.updated",
            resource_type=item.item_type,
            resource_id=str(item.id),
            details={"previous_status": previous["status"], "status": normalized},
        )
        return await self.get_item(actor, item_id)

    async def update_collection(
        self,
        actor: AuthContext,
        item_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        description_provided: bool = False,
    ) -> dict[str, Any]:
        previous = await self.get_item(actor, item_id)
        if previous["item_type"] != "collection":
            raise AdminValidationError("only collections can use this update")
        if title is None and not description_provided:
            raise AdminValidationError("collection update has no changes")

        item = await self._session.get(Item, item_id)
        assert item is not None
        changed_fields: list[str] = []
        if title is not None:
            item.title = normalize_required_text(title, "collection title", 255)
            changed_fields.append("title")
        if description_provided:
            normalized_description = (
                description.strip() if description is not None else ""
            )
            if len(normalized_description) > 2_000:
                raise AdminValidationError(
                    "collection description must be at most 2000 characters"
                )
            metadata = dict(item.metadata_)
            if normalized_description:
                metadata["description"] = normalized_description
            else:
                metadata.pop("description", None)
            item.metadata_ = metadata
            changed_fields.append("description")

        await self._session.flush()
        await self._audit.record(
            actor,
            action="collection.updated",
            resource_type="collection",
            resource_id=str(item.id),
            details={"changed_fields": changed_fields},
        )
        return await self.get_item(actor, item.id)

    async def retry_item(self, actor: AuthContext, item_id: UUID) -> dict[str, Any]:
        payload = await self.get_item(actor, item_id)
        if payload["status"] != "failed":
            raise AdminConflictError("only failed items can be retried")
        origin = await self._session.scalar(
            select(ItemOrigin).where(
                ItemOrigin.item_id == item_id, ItemOrigin.deleted_at.is_(None)
            )
        )
        if origin is None:
            item = await self._session.get(Item, item_id)
            assert item is not None
            item.status = "pending"
            return {"item": await self.get_item(actor, item.id), "sync_run": None}
        run = await PluginService(
            self._session,
            credential_encryption_key=self._plugin_encryption_key,
            audit=self._audit,
        ).trigger_binding(actor, origin.binding_id)
        return {"item": payload, "sync_run": run}

    async def delete_item(self, actor: AuthContext, item_id: UUID) -> None:
        require_tenant_permission(actor, ITEM_MANAGE_PERMISSION)
        payload = await self.get_item(actor, item_id)
        if self._vector_store is not None and payload["item_type"] == "document":
            await self._vector_store.soft_delete_document_points(str(item_id))
        await ItemService(self._session).soft_delete_item(item_id, actor=actor)
        await self._audit.record(
            actor,
            action=f"{payload['item_type']}.deleted",
            resource_type=payload["item_type"],
            resource_id=str(item_id),
        )

    @staticmethod
    def _payload(item: Item) -> dict[str, Any]:
        processing = item.metadata_.get("processing")
        description = item.metadata_.get("description")
        origins = [origin for origin in item.origins if origin.deleted_at is None]
        return {
            "id": str(item.id),
            "item_type": item.item_type,
            "document_type": item.document_type,
            "title": item.title,
            "mime_type": item.mime_type,
            "size_bytes": item.size_bytes,
            "parent_item_id": str(item.parent_item_id) if item.parent_item_id else None,
            "parent_relation": item.parent_relation,
            "status": item.status,
            "indexed": isinstance(processing, dict)
            and processing.get("index_schema_version") is not None,
            "metadata": (
                {"description": description} if isinstance(description, str) else {}
            ),
            "inherit_access": item.inherit_access,
            "created_by_user_id": (
                str(item.created_by_user_id) if item.created_by_user_id else None
            ),
            "created_at": timestamp(item.created_at),
            "updated_at": timestamp(item.updated_at),
            "origins": [
                {
                    "id": str(origin.id),
                    "external_id": origin.external_id,
                    "source_url": origin.source_url,
                    "binding_id": str(origin.binding_id),
                    "connection": {
                        "id": str(origin.binding.connection.id),
                        "display_name": origin.binding.connection.display_name,
                        "plugin_key": origin.binding.connection.plugin_key,
                    },
                }
                for origin in origins
            ],
        }


__all__ = ["AdminItemService"]
