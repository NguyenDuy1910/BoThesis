"""Canonical hierarchical Item lifecycle and provenance mapping."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import and_, false, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bothesis.db.models import (
    CollectionAccess,
    Conversation,
    Item,
    ItemOrigin,
    ItemUpload,
    Message,
    MessageItem,
    PluginBinding,
    PluginConnection,
)
from bothesis.services import (
    ACTIVE_STATUS,
    MESSAGE_ITEM_RELATIONS,
    AuthContext,
    AuthService,
    DocumentNotFoundError,
    InvalidDocumentStateError,
)

_ITEM_STATUSES = {"pending", "processing", "ready", "failed", "unsupported", "deleted"}
_PARENT_RELATIONS = {"contains", "child", "attachment", "embedded"}


class ItemService:
    """Own canonical Items; ingestion details are represented by Item Origins."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def origin_item_id(binding_id: UUID, identity_key: str) -> UUID:
        normalized = _required_text(identity_key, "external identity")
        return uuid5(NAMESPACE_URL, f"bothesis:item-origin:{binding_id}:{normalized}")

    @staticmethod
    def upload_collection_id(tenant_id: UUID, user_id: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, f"bothesis:upload-collection:{tenant_id}:{user_id}")

    async def create_collection(
        self,
        *,
        tenant_id: UUID,
        title: str,
        created_by_user_id: UUID,
        parent_item_id: UUID | None = None,
        inherit_access: bool = True,
        metadata: Mapping[str, Any] | None = None,
        item_id: UUID | None = None,
    ) -> Item:
        await AuthService(self._session).get_tenant(tenant_id)
        await AuthService(self._session).get_user(created_by_user_id)
        await self._validate_parent(
            tenant_id=tenant_id,
            parent_item_id=parent_item_id,
            child_type="collection",
        )
        item = Item(
            id=item_id or uuid4(),
            tenant_id=tenant_id,
            item_type="collection",
            parent_item_id=parent_item_id,
            parent_relation="contains" if parent_item_id else None,
            title=_required_text(title, "collection title"),
            metadata_=dict(metadata or {}),
            inherit_access=bool(inherit_access),
            status="ready",
            created_by_user_id=created_by_user_id,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def create_document(
        self,
        *,
        tenant_id: UUID,
        parent_item_id: UUID,
        title: str,
        document_type: str,
        created_by_user_id: UUID | None,
        parent_relation: str = "contains",
        mime_type: str | None = None,
        size_bytes: int | None = None,
        storage_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        status: str = "pending",
        item_id: UUID | None = None,
    ) -> Item:
        await self._validate_parent(
            tenant_id=tenant_id,
            parent_item_id=parent_item_id,
            child_type="document",
        )
        item = Item(
            id=item_id or uuid4(),
            tenant_id=tenant_id,
            item_type="document",
            parent_item_id=parent_item_id,
            parent_relation=_parent_relation(parent_relation),
            document_type=_document_type(document_type),
            title=_required_text(title, "document title"),
            mime_type=_optional_text(mime_type, max_length=255),
            size_bytes=_size(size_bytes),
            storage_key=_optional_text(storage_key),
            metadata_=dict(metadata or {}),
            status=_item_status(status),
            created_by_user_id=created_by_user_id,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def create_or_get_personal_upload(
        self,
        owner_user_id: UUID,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        file_name: str,
        mime_type: str,
        size_bytes: int,
        document_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[Item, bool]:
        await AuthService(self._session).get_user(owner_user_id)
        await AuthService(self._session).get_tenant(tenant_id)
        normalized_key = _required_text(
            idempotency_key, "upload idempotency key", max_length=128
        )
        normalized_name = _required_text(file_name, "file name", max_length=240)
        normalized_mime = _required_text(mime_type, "mime type", max_length=255).casefold()
        if size_bytes < 1:
            raise ValueError("upload size must be greater than zero")

        collection_id = self.upload_collection_id(tenant_id, owner_user_id)
        await self._session.execute(
            insert(Item)
            .values(
                id=collection_id,
                tenant_id=tenant_id,
                item_type="collection",
                title="My uploads",
                metadata_={"system_kind": "personal_uploads"},
                inherit_access=False,
                status="ready",
                created_by_user_id=owner_user_id,
            )
            .on_conflict_do_nothing(index_elements=[Item.id])
        )
        await self._session.execute(
            insert(CollectionAccess)
            .values(
                item_id=collection_id,
                principal_type="user",
                principal_id=owner_user_id,
                role="owner",
                created_by_user_id=owner_user_id,
            )
            .on_conflict_do_update(
                index_elements=[
                    CollectionAccess.item_id,
                    CollectionAccess.principal_type,
                    CollectionAccess.principal_id,
                ],
                set_={"role": "owner", "deleted_at": None},
            )
        )

        item_id = uuid5(
            NAMESPACE_URL,
            f"bothesis:upload:{tenant_id}:{owner_user_id}:{normalized_key}",
        )
        storage_key = f"tenants/{tenant_id}/items/{item_id}/raw"
        inserted_id = await self._session.scalar(
            insert(Item)
            .values(
                id=item_id,
                tenant_id=tenant_id,
                item_type="document",
                parent_item_id=collection_id,
                parent_relation="contains",
                document_type=_document_type(document_type),
                title=normalized_name,
                mime_type=normalized_mime,
                size_bytes=size_bytes,
                storage_key=storage_key,
                metadata_={**dict(metadata or {}), "file_name": normalized_name},
                status="pending",
                created_by_user_id=owner_user_id,
            )
            .on_conflict_do_nothing(index_elements=[Item.id])
            .returning(Item.id)
        )
        await self._session.execute(
            insert(ItemUpload)
            .values(
                item_id=item_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                idempotency_key=normalized_key,
                status="pending",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ItemUpload.tenant_id,
                    ItemUpload.owner_user_id,
                    ItemUpload.idempotency_key,
                ]
            )
        )
        item = await self._session.scalar(
            select(Item).options(joinedload(Item.upload)).where(Item.id == item_id)
        )
        if item is None or item.upload is None:
            raise InvalidDocumentStateError("upload idempotency record is unavailable")
        if (
            item.tenant_id != tenant_id
            or item.parent_item_id != collection_id
            or item.title != normalized_name
            or item.mime_type != normalized_mime
            or item.size_bytes != size_bytes
            or item.status == "deleted"
        ):
            raise InvalidDocumentStateError(
                "upload idempotency key was reused with different file metadata"
            )
        await self._session.flush()
        return item, inserted_id is not None

    async def upsert_ingested_item(
        self,
        binding_id: UUID,
        external_id: str,
        *,
        canonical_external_id: str | None = None,
        item_type: str,
        title: str,
        document_type: str | None = None,
        parent_external_id: str | None = None,
        parent_relation: str | None = None,
        source_url: str | None = None,
        external_version: str | None = None,
        etag: str | None = None,
        external_updated_at: datetime | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        storage_key: str | None = None,
        status: str = "ready",
    ) -> Item:
        binding = await self._binding(binding_id)
        normalized_external_id = _required_text(external_id, "external id")
        normalized_type = _item_type(item_type)
        identity_key = _required_text(
            canonical_external_id or normalized_external_id, "canonical external id"
        )
        origin_metadata = dict(metadata or {})
        origin_metadata["canonical_external_id"] = identity_key
        now = datetime.now(UTC)

        if normalized_type == "collection":
            item = binding.target_item
        else:
            parent_id = binding.target_item_id
            if parent_external_id:
                parent_origin = await self._origin_by_identity(
                    binding.id, parent_external_id
                )
                if parent_origin is not None:
                    parent_id = parent_origin.item_id
            item_id = self.origin_item_id(binding.id, identity_key)
            values = {
                "tenant_id": binding.connection.tenant_id,
                "item_type": "document",
                "parent_item_id": parent_id,
                "parent_relation": _parent_relation(parent_relation or "child"),
                "document_type": _document_type(document_type or "plain_text"),
                "title": _required_text(title, "item title"),
                "mime_type": _optional_text(mime_type, max_length=255),
                "size_bytes": _size(size_bytes),
                "storage_key": _optional_text(storage_key),
                "metadata_": dict(metadata or {}),
                "status": _item_status(status),
                "deleted_at": None,
            }
            await self._validate_parent(
                tenant_id=binding.connection.tenant_id,
                parent_item_id=parent_id,
                child_type="document",
            )
            item = await self._session.get(Item, item_id, with_for_update=True)
            if item is None:
                item = Item(id=item_id, **values)
                self._session.add(item)
            else:
                for attribute, value in values.items():
                    setattr(item, attribute, value)
            await self._session.flush()

        existing_origin = await self._session.scalar(
            select(ItemOrigin)
            .where(
                ItemOrigin.binding_id == binding.id,
                ItemOrigin.external_id == normalized_external_id,
            )
            .with_for_update()
        )
        origin_values = {
            "item_id": item.id,
            "external_version": _optional_text(external_version),
            "etag": _optional_text(etag),
            "external_updated_at": external_updated_at,
            "source_url": _optional_text(source_url),
            "metadata_": origin_metadata,
            "last_seen_at": now,
            "deleted_at": None,
        }
        if existing_origin is None:
            self._session.add(
                ItemOrigin(
                    binding_id=binding.id,
                    external_id=normalized_external_id,
                    **origin_values,
                )
            )
        else:
            for attribute, value in origin_values.items():
                setattr(existing_origin, attribute, value)
        await self._session.flush()
        return item

    async def soft_delete_origin(
        self, binding_id: UUID, external_id: str
    ) -> Item | None:
        origin = await self._session.scalar(
            select(ItemOrigin)
            .options(joinedload(ItemOrigin.item))
            .where(
                ItemOrigin.binding_id == binding_id,
                ItemOrigin.external_id == _required_text(external_id, "external id"),
                ItemOrigin.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if origin is None:
            return None
        now = datetime.now(UTC)
        origin.deleted_at = now
        if origin.item.item_type == "document":
            origin.item.status = "deleted"
            origin.item.deleted_at = now
        await self._session.flush()
        return origin.item

    async def get_item(self, item_id: UUID, *, access: AuthContext) -> Item:
        from bothesis.services.collection_access import CollectionAccessService

        return await CollectionAccessService(self._session).require_item_access(
            item_id, access=access
        )

    async def get_item_by_canonical_id(
        self, item_id: str, *, access: AuthContext
    ) -> Item:
        try:
            parsed_id = UUID(item_id.strip())
        except (AttributeError, ValueError) as exc:
            raise DocumentNotFoundError("item not found") from exc
        return await self.get_item(parsed_id, access=access)

    async def list_items(
        self,
        *,
        access: AuthContext,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Item]:
        from bothesis.services.collection_access import CollectionAccessService

        if not 1 <= limit <= 1_000 or offset < 0:
            raise ValueError("invalid item pagination")
        allowed = await CollectionAccessService(self._session).allowed_collection_ids(access)
        if not allowed:
            return []
        visible = (
            select(Item.id.label("item_id"))
            .where(Item.id.in_(allowed))
            .cte("visible_items", recursive=True)
        )
        child = Item.__table__.alias("child_item")
        visible = visible.union_all(
            select(child.c.id).where(
                child.c.parent_item_id == visible.c.item_id,
                child.c.status != "deleted",
                child.c.deleted_at.is_(None),
                or_(
                    child.c.item_type == "document",
                    child.c.id.in_(allowed),
                ),
            )
        )
        ids = select(visible.c.item_id).distinct().subquery()
        result = await self._session.scalars(
            select(Item)
            .join(ids, ids.c.item_id == Item.id)
            .where(Item.status != "deleted", Item.deleted_at.is_(None))
            .order_by(Item.updated_at.desc(), Item.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def get_owned_upload(
        self,
        item_id: UUID,
        owner_user_id: UUID,
        tenant_id: UUID,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Item:
        statement = (
            select(Item)
            .join(ItemUpload, ItemUpload.item_id == Item.id)
            .options(joinedload(Item.upload))
            .where(
                Item.id == item_id,
                ItemUpload.owner_user_id == owner_user_id,
                ItemUpload.tenant_id == tenant_id,
            )
        )
        if not include_deleted:
            statement = statement.where(Item.status != "deleted", Item.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update(of=Item)
        item = await self._session.scalar(statement)
        if item is None or item.upload is None:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        return item

    async def mark_upload_available(
        self,
        item_id: UUID,
        owner_user_id: UUID,
        tenant_id: UUID,
        *,
        storage_metadata: Mapping[str, Any] | None = None,
    ) -> Item:
        item = await self.get_owned_upload(
            item_id, owner_user_id, tenant_id, include_deleted=True, for_update=True
        )
        assert item.upload is not None
        if item.status == "deleted":
            raise DocumentNotFoundError(f"item not found: {item_id}")
        if item.upload.status == "available":
            return item
        if item.upload.status not in {"pending", "failed"}:
            raise InvalidDocumentStateError("item is not awaiting uploaded content")
        item.status = "ready"
        item.upload.status = "available"
        item.upload.error_code = None
        item.upload.uploaded_at = datetime.now(UTC)
        if storage_metadata:
            item.metadata_ = {**dict(item.metadata_), "storage": dict(storage_metadata)}
        await self._session.flush()
        return item

    async def mark_upload_failed(
        self,
        item_id: UUID,
        owner_user_id: UUID,
        tenant_id: UUID,
        *,
        error_code: str,
    ) -> Item:
        item = await self.get_owned_upload(item_id, owner_user_id, tenant_id)
        assert item.upload is not None
        if item.upload.status == "available":
            return item
        item.upload.status = "failed"
        item.upload.error_code = _required_text(error_code, "upload error code", max_length=128)
        item.status = "failed"
        await self._session.flush()
        return item

    async def merge_metadata(self, item_id: UUID, values: Mapping[str, Any]) -> Item:
        item = await self._get_internal(item_id)
        item.metadata_ = {**dict(item.metadata_), **dict(values)}
        await self._session.flush()
        return item

    async def mark_processing(self, item_id: UUID) -> Item:
        return await self._set_status(item_id, "processing")

    async def mark_ready(self, item_id: UUID) -> Item:
        return await self._set_status(item_id, "ready")

    async def mark_failed(self, item_id: UUID) -> Item:
        return await self._set_status(item_id, "failed")

    async def link_message(
        self,
        message_id: UUID,
        item_id: UUID,
        relation_type: str,
        *,
        access: AuthContext,
        position: int = 0,
    ) -> MessageItem:
        relation = relation_type.strip().casefold()
        if relation not in MESSAGE_ITEM_RELATIONS or position < 0:
            raise ValueError("invalid message-item relation")
        message_exists = await self._session.scalar(
            select(Message.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Conversation.user_id == access.user_id,
                Conversation.tenant_id == access.tenant_id,
            )
        )
        if message_exists is None:
            raise DocumentNotFoundError(f"message not found: {message_id}")
        await self.get_item(item_id, access=access)
        link = await self._session.scalar(
            insert(MessageItem)
            .values(
                message_id=message_id,
                item_id=item_id,
                relation_type=relation,
                position=position,
            )
            .on_conflict_do_update(
                index_elements=[
                    MessageItem.message_id,
                    MessageItem.item_id,
                    MessageItem.relation_type,
                ],
                set_={"position": position, "deleted_at": None},
            )
            .returning(MessageItem)
        )
        if link is None:
            raise InvalidDocumentStateError("message-item link was not stored")
        return link

    async def soft_delete_item(self, item_id: UUID, *, actor: AuthContext) -> Item:
        from bothesis.services.collection_access import CollectionAccessService

        item = await CollectionAccessService(self._session).require_item_access(
            item_id, access=actor, minimum_role="editor"
        )
        item.status = "deleted"
        item.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return item

    async def _set_status(self, item_id: UUID, status: str) -> Item:
        item = await self._get_internal(item_id)
        if item.status == "deleted":
            raise InvalidDocumentStateError("cannot update a deleted item")
        item.status = _item_status(status)
        await self._session.flush()
        return item

    async def _get_internal(self, item_id: UUID) -> Item:
        item = await self._session.get(Item, item_id)
        if item is None:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        return item

    async def _binding(self, binding_id: UUID) -> PluginBinding:
        binding = await self._session.scalar(
            select(PluginBinding)
            .options(
                joinedload(PluginBinding.connection),
                joinedload(PluginBinding.target_item),
            )
            .where(PluginBinding.id == binding_id)
        )
        unavailable = (
            binding is None
            or binding.status != ACTIVE_STATUS
            or binding.deleted_at is not None
            or binding.connection.status != ACTIVE_STATUS
            or binding.connection.deleted_at is not None
            or binding.target_item.item_type != "collection"
            or binding.target_item.status == "deleted"
            or binding.target_item.deleted_at is not None
            or binding.target_item.tenant_id != binding.connection.tenant_id
        )
        if unavailable:
            raise DocumentNotFoundError(f"active plugin binding not found: {binding_id}")
        assert binding is not None
        return binding

    async def _origin_by_identity(
        self, binding_id: UUID, identity: str
    ) -> ItemOrigin | None:
        normalized = _required_text(identity, "parent external id")
        return await self._session.scalar(
            select(ItemOrigin).where(
                ItemOrigin.binding_id == binding_id,
                ItemOrigin.deleted_at.is_(None),
                or_(
                    ItemOrigin.external_id == normalized,
                    ItemOrigin.metadata_["canonical_external_id"].astext == normalized,
                ),
            )
        )

    async def _validate_parent(
        self,
        *,
        tenant_id: UUID,
        parent_item_id: UUID | None,
        child_type: str,
    ) -> Item | None:
        if parent_item_id is None:
            if child_type != "collection":
                raise InvalidDocumentStateError("a Document must have a parent Item")
            return None
        parent = await self._session.scalar(
            select(Item).where(
                Item.id == parent_item_id,
                Item.tenant_id == tenant_id,
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if parent is None:
            raise InvalidDocumentStateError(f"parent item is unavailable: {parent_item_id}")
        if child_type == "collection" and parent.item_type != "collection":
            raise InvalidDocumentStateError("a Document may not contain a Collection")
        return parent


def _item_type(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in {"collection", "document"}:
        raise ValueError("item type must be collection or document")
    return normalized


def _document_type(value: str) -> str:
    return _required_text(value, "document type", max_length=64).casefold()


def _parent_relation(value: str) -> str:
    normalized = _required_text(value, "parent relation", max_length=32).casefold()
    if normalized not in _PARENT_RELATIONS:
        raise ValueError("invalid parent relation")
    return normalized


def _item_status(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in _ITEM_STATUSES:
        raise ValueError("invalid item status")
    return normalized


def _size(value: int | None) -> int | None:
    if value is not None and value < 0:
        raise ValueError("item size must not be negative")
    return value


def _required_text(
    value: str, field_name: str, *, max_length: int | None = None
) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if max_length is not None and len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    return normalized


def _optional_text(value: str | None, *, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    return _required_text(value, "value", max_length=max_length)


__all__ = ["ItemService"]
