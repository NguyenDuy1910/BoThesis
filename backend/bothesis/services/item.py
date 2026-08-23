"""Permission-aware persistence for canonical source Items."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, false, not_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import Select

from bothesis.db.models import (
    Connector,
    ConnectorScope,
    Conversation,
    Item,
    ItemUpload,
    Message,
    MessageItem,
)
from bothesis.services import (
    ACTIVE_STATUS,
    AuthContext,
    AuthService,
    AuthorizationError,
    DocumentNotFoundError,
    InvalidDocumentStateError,
    KNOWLEDGE_READ_PERMISSION,
    MESSAGE_ITEM_RELATIONS,
    SOURCE_MANAGE_PERMISSION,
)


class ItemService:
    """Own Item lifecycle, hierarchy, lineage, and materialized ACL state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def connector_item_id(connector_id: int, external_id: str) -> UUID:
        normalized = _required_text(external_id, "external id")
        return uuid5(NAMESPACE_URL, f"bothesis:item:{connector_id}:{normalized}")

    async def create_or_get_personal_upload(
        self,
        owner_user_id: UUID,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        file_name: str,
        mime_type: str,
        size_bytes: int,
        document_kind: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[Item, bool]:
        await AuthService(self._session).get_user(owner_user_id)
        await AuthService(self._session).get_tenant(tenant_id)
        normalized_key = _required_text(
            idempotency_key, "upload idempotency key", max_length=128
        )
        normalized_name = _required_text(file_name, "file name", max_length=240)
        normalized_mime = _required_text(
            mime_type, "mime type", max_length=255
        ).casefold()
        _validate_size(size_bytes)
        if size_bytes < 1:
            raise ValueError("upload size must be greater than zero")

        item_id = uuid5(
            NAMESPACE_URL,
            f"bothesis:upload:{tenant_id}:{owner_user_id}:{normalized_key}",
        )
        storage_key = f"tenants/{tenant_id}/items/{item_id}/raw"
        inserted_id = await self._session.scalar(
            insert(Item)
            .values(
                id=item_id,
                item_type="document",
                document_kind=_required_text(document_kind, "document kind", max_length=32),
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
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
            select(Item)
            .options(joinedload(Item.upload))
            .where(Item.id == item_id)
        )
        if item is None or item.upload is None:
            raise InvalidDocumentStateError("upload idempotency record is unavailable")
        if (
            item.tenant_id != tenant_id
            or item.owner_user_id != owner_user_id
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
                Item.owner_user_id == owner_user_id,
                Item.tenant_id == tenant_id,
            )
        )
        if not include_deleted:
            statement = statement.where(Item.status != "deleted")
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
        content_sha256: str | None,
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
        item.content_sha256 = _content_sha256(content_sha256)
        item.status = "ready"
        item.upload.status = "available"
        item.upload.error_code = None
        item.upload.uploaded_at = datetime.now(UTC)
        if storage_metadata:
            item.metadata_ = {
                **dict(item.metadata_),
                "storage": dict(storage_metadata),
            }
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
        item.upload.error_code = _required_text(
            error_code, "upload error code", max_length=128
        )
        item.status = "failed"
        await self._session.flush()
        return item

    async def upsert_external_item(
        self,
        connector_scope_id: int,
        external_id: str,
        *,
        canonical_source_id: str | None = None,
        item_type: str,
        title: str,
        document_kind: str | None = None,
        collection_kind: str | None = None,
        parent_source_id: str | None = None,
        source_url: str | None = None,
        external_version: str | None = None,
        etag: str | None = None,
        external_updated_at: datetime | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        storage_key: str | None = None,
        content_sha256: str | None = None,
        allowed_principal_tokens: Iterable[str] = (),
        denied_principal_tokens: Iterable[str] = (),
        status: str = "ready",
        require_active_scope: bool = True,
    ) -> Item:
        scope = await self._scope(
            connector_scope_id, require_active=require_active_scope
        )
        connector = scope.connector
        normalized_external_id = _required_text(external_id, "external id")
        identity_key = _required_text(
            canonical_source_id or normalized_external_id, "canonical source item id"
        )
        item_id = self.connector_item_id(connector.id, identity_key)
        parent_item_id = (
            self.connector_item_id(connector.id, parent_source_id)
            if parent_source_id
            else None
        )
        if parent_item_id is not None:
            parent = await self._session.get(Item, parent_item_id)
            if parent is None or parent.connector_id != connector.id:
                raise InvalidDocumentStateError(
                    f"parent item is not persisted: {parent_source_id}"
                )
        values: dict[str, Any] = {
            "item_type": _item_type(item_type),
            "document_kind": _optional_text(document_kind, max_length=32),
            "collection_kind": _optional_text(collection_kind, max_length=32),
            "tenant_id": connector.tenant_id,
            "owner_user_id": (
                connector.owner_user_id if connector.owner_type == "user" else None
            ),
            "connector_id": connector.id,
            "connector_scope_id": scope.id,
            "external_id": normalized_external_id,
            "external_version": _optional_text(external_version),
            "etag": _optional_text(etag),
            "external_updated_at": external_updated_at,
            "parent_item_id": parent_item_id,
            "title": _required_text(title, "item title"),
            "source_url": _optional_text(source_url),
            "mime_type": _optional_text(mime_type, max_length=255),
            "size_bytes": size_bytes,
            "storage_key": _optional_text(storage_key),
            "content_sha256": _content_sha256(content_sha256),
            "allowed_principal_tokens": _normalize_tokens(allowed_principal_tokens),
            "denied_principal_tokens": _normalize_tokens(denied_principal_tokens),
            "metadata_": dict(metadata or {}),
            "status": _item_status(status),
            "deleted_at": None,
        }
        _validate_item_kinds(
            values["item_type"], values["document_kind"], values["collection_kind"]
        )
        _validate_size(size_bytes)
        item = await self._session.get(Item, item_id, with_for_update=True)
        if item is None:
            item = Item(id=item_id, **values)
            self._session.add(item)
        else:
            for attribute, value in values.items():
                setattr(item, attribute, value)
        await self._session.flush()
        return item

    async def soft_delete_external_item(
        self, connector_id: int, external_id: str
    ) -> Item | None:
        item = await self._session.scalar(
            select(Item).where(
                Item.id == self.connector_item_id(connector_id, external_id),
                Item.connector_id == connector_id,
            )
        )
        if item is None or item.status == "deleted":
            return item
        item.status = "deleted"
        item.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return item

    async def merge_metadata(self, item_id: UUID, values: Mapping[str, Any]) -> Item:
        item = await self._get_internal(item_id)
        item.metadata_ = {**dict(item.metadata_), **dict(values)}
        await self._session.flush()
        return item

    async def set_content_sha256(self, item_id: UUID, value: str) -> Item:
        item = await self._get_internal(item_id)
        normalized = _content_sha256(value)
        if normalized is None:
            raise ValueError("content sha256 is required")
        if item.content_sha256 is not None and item.content_sha256 != normalized:
            raise InvalidDocumentStateError("item content fingerprint changed")
        item.content_sha256 = normalized
        await self._session.flush()
        return item

    async def mark_processing(self, item_id: UUID) -> Item:
        return await self._set_status(item_id, "processing")

    async def mark_ready(self, item_id: UUID) -> Item:
        return await self._set_status(item_id, "ready")

    async def mark_failed(self, item_id: UUID) -> Item:
        return await self._set_status(item_id, "failed")

    async def get_item(self, item_id: UUID, *, access: AuthContext) -> Item:
        item = await self._session.scalar(
            self._visible_items(access).where(Item.id == item_id)
        )
        if item is None:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        return item

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
        connector_ids: Iterable[int] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Item]:
        if not 1 <= limit <= 1_000 or offset < 0:
            raise ValueError("invalid item pagination")
        statement = self._visible_items(access)
        if connector_ids is not None:
            ids = sorted(set(connector_ids))
            if not ids:
                return []
            statement = statement.where(Item.connector_id.in_(ids))
        result = await self._session.scalars(
            statement.order_by(Item.updated_at.desc(), Item.id).limit(limit).offset(offset)
        )
        return list(result)

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
            .where(Message.id == message_id, Conversation.user_id == access.user_id)
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
        item = await self._session.get(Item, item_id)
        if item is None or item.status == "deleted":
            raise DocumentNotFoundError(f"item not found: {item_id}")
        owns = item.owner_user_id == actor.user_id and item.tenant_id == actor.tenant_id
        manages = item.tenant_id == actor.tenant_id and (
            item.created_by_user_id == actor.user_id
            or actor.has_permissions(SOURCE_MANAGE_PERMISSION)
        )
        if not owns and not manages:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        item.status = "deleted"
        item.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return item

    def _visible_items(self, access: AuthContext) -> Select[tuple[Item]]:
        if access.tenant_id is None:
            return select(Item).where(false())
        personal = and_(
            Item.tenant_id == access.tenant_id,
            Item.owner_user_id == access.user_id,
        )
        predicate = personal
        if access.has_permissions(KNOWLEDGE_READ_PERMISSION):
            tenant_access: Any = and_(
                Item.tenant_id == access.tenant_id,
                Item.owner_user_id.is_(None),
            )
            if not access.is_admin:
                tokens = sorted({"public", *access.principal_tokens})
                tenant_access = and_(
                    tenant_access,
                    Item.allowed_principal_tokens.overlap(tokens),
                    not_(Item.denied_principal_tokens.overlap(tokens)),
                )
            predicate = or_(personal, tenant_access)
        active_connector = or_(
            Item.connector_id.is_(None),
            and_(Connector.status == ACTIVE_STATUS, ConnectorScope.status == ACTIVE_STATUS),
        )
        return (
            select(Item)
            .outerjoin(Connector, Connector.id == Item.connector_id)
            .outerjoin(ConnectorScope, ConnectorScope.id == Item.connector_scope_id)
            .where(Item.status != "deleted", Item.deleted_at.is_(None), active_connector, predicate)
        )

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

    async def _scope(
        self, scope_id: int, *, require_active: bool
    ) -> ConnectorScope:
        scope = await self._session.scalar(
            select(ConnectorScope)
            .options(joinedload(ConnectorScope.connector))
            .where(ConnectorScope.id == scope_id)
        )
        unavailable = (
            scope is None
            or scope.status == "deleted"
            or scope.connector.status == "deleted"
            or (
                require_active
                and (
                    scope.status != ACTIVE_STATUS
                    or scope.connector.status != ACTIVE_STATUS
                )
            )
        )
        if unavailable:
            qualifier = "active " if require_active else ""
            raise DocumentNotFoundError(
                f"{qualifier}connector scope not found: {scope_id}"
            )
        assert scope is not None
        return scope


def _item_type(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in {"collection", "document", "file"}:
        raise ValueError("item type must be collection, document, or file")
    return normalized


def _item_status(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in {"pending", "processing", "ready", "failed", "unsupported", "deleted"}:
        raise ValueError("invalid item status")
    return normalized


def _validate_item_kinds(
    item_type: str, document_kind: str | None, collection_kind: str | None
) -> None:
    valid = (
        item_type == "document" and document_kind is not None and collection_kind is None
    ) or (
        item_type == "collection" and collection_kind is not None and document_kind is None
    ) or (item_type == "file" and document_kind is None and collection_kind is None)
    if not valid:
        raise ValueError("item kind does not match item type")


def _normalize_tokens(values: Iterable[str]) -> list[str]:
    return sorted(
        {_required_text(value, "principal token", max_length=512).casefold() for value in values}
    )


def _validate_size(size_bytes: int | None) -> None:
    if size_bytes is not None and size_bytes < 0:
        raise ValueError("item size must not be negative")


def _content_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError("content sha256 must be a hexadecimal digest")
    return normalized


def _required_text(value: str, field_name: str, *, max_length: int | None = None) -> str:
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
