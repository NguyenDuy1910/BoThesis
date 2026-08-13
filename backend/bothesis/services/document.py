"""Permission-aware PostgreSQL document lifecycle service."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, not_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql import Select

from bothesis.db.models import (
    Connector,
    ConnectorScope,
    Conversation,
    Document,
    DocumentBlob,
    DocumentChunk,
    Message,
    MessageDocument,
    SyncRun,
)
from bothesis.services.auth import (
    ACTIVE_STATUS,
    AuthContext,
    AuthService,
    AuthorizationError,
)

LOCAL_DOCUMENT_ORIGINS = frozenset({"upload", "generated"})
MESSAGE_DOCUMENT_RELATIONS = frozenset({"attachment", "reference", "output"})
KNOWLEDGE_READ_PERMISSION = "knowledge.read"
SOURCE_MANAGE_PERMISSION = "source.manage"


class DocumentServiceError(Exception):
    """Base exception for durable document service failures."""


class DocumentNotFoundError(DocumentServiceError):
    """Raised for missing and inaccessible documents to prevent enumeration."""


class InvalidDocumentStateError(DocumentServiceError):
    """Raised when a lifecycle or lineage transition is invalid."""


@dataclass(frozen=True, slots=True)
class DocumentChunkInput:
    """Canonical chunk content written to PostgreSQL before vector indexing."""

    content: str
    token_count: int | None = None
    start_page_number: int | None = None
    end_page_number: int | None = None
    heading_path: tuple[str, ...] | None = None
    metadata: Mapping[str, Any] | None = None


class DocumentService:
    """Manage documents while preserving ownership, ACL, and source lineage."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_personal_document(
        self,
        owner_user_id: UUID,
        *,
        origin: str,
        title: str | None = None,
        source_url: str | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        raw_storage_key: str | None = None,
        parent_document_id: UUID | None = None,
    ) -> Document:
        await AuthService(self._session).get_user(owner_user_id)
        normalized_origin = _local_origin(origin)
        _validate_size(size_bytes)
        if parent_document_id is not None:
            await self._validate_parent(
                parent_document_id,
                owner_user_id=owner_user_id,
                tenant_id=None,
                connector_scope_id=None,
                generation=None,
            )

        document = Document(
            owner_user_id=owner_user_id,
            tenant_id=None,
            connector_scope_id=None,
            generation=None,
            origin=normalized_origin,
            title=_optional_text(title),
            source_url=_optional_text(source_url),
            mime_type=_optional_text(mime_type, max_length=255),
            size_bytes=size_bytes,
            metadata_=dict(metadata or {}),
            raw_storage_key=_optional_text(raw_storage_key),
            parent_document_id=parent_document_id,
            created_by_user_id=owner_user_id,
        )
        self._session.add(document)
        await self._session.flush()
        return document

    async def create_enterprise_document(
        self,
        tenant_id: UUID,
        *,
        origin: str,
        created_by_user_id: UUID,
        title: str | None = None,
        source_url: str | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        raw_storage_key: str | None = None,
        parent_document_id: UUID | None = None,
        allowed_principal_tokens: Iterable[str] = (),
        denied_principal_tokens: Iterable[str] = (),
    ) -> Document:
        await AuthService(self._session).get_tenant(tenant_id)
        creator = await AuthService(self._session).get_context(created_by_user_id)
        if creator.tenant_id != tenant_id:
            raise AuthorizationError("document creator is outside the tenant")
        if not creator.has_permissions(SOURCE_MANAGE_PERMISSION):
            raise AuthorizationError("source.manage permission is required")
        normalized_origin = _local_origin(origin)
        _validate_size(size_bytes)
        if parent_document_id is not None:
            await self._validate_parent(
                parent_document_id,
                owner_user_id=None,
                tenant_id=tenant_id,
                connector_scope_id=None,
                generation=None,
            )

        document = Document(
            owner_user_id=None,
            tenant_id=tenant_id,
            connector_scope_id=None,
            generation=None,
            origin=normalized_origin,
            title=_optional_text(title),
            source_url=_optional_text(source_url),
            mime_type=_optional_text(mime_type, max_length=255),
            size_bytes=size_bytes,
            metadata_=dict(metadata or {}),
            raw_storage_key=_optional_text(raw_storage_key),
            parent_document_id=parent_document_id,
            allowed_principal_tokens=_normalize_tokens(allowed_principal_tokens),
            denied_principal_tokens=_normalize_tokens(denied_principal_tokens),
            created_by_user_id=created_by_user_id,
        )
        self._session.add(document)
        await self._session.flush()
        return document

    async def upsert_external_document(
        self,
        connector_scope_id: int,
        generation: int,
        external_id: str,
        *,
        title: str | None = None,
        source_url: str | None = None,
        external_version: str | None = None,
        etag: str | None = None,
        external_updated_at: datetime | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        raw_storage_key: str | None = None,
        parent_document_id: UUID | None = None,
        allowed_principal_tokens: Iterable[str] = (),
        denied_principal_tokens: Iterable[str] = (),
    ) -> Document:
        """Create or refresh one snapshot from a trusted connector worker."""

        if generation < 1:
            raise ValueError("generation must be at least one")
        normalized_external_id = _required_text(external_id, "external id")
        _validate_size(size_bytes)
        scope = await self._active_scope(connector_scope_id)
        runnable_sync = await self._session.scalar(
            select(SyncRun.id).where(
                SyncRun.connector_scope_id == connector_scope_id,
                SyncRun.generation == generation,
                SyncRun.status.in_(("pending", "running", "completed")),
            )
        )
        if runnable_sync is None:
            raise InvalidDocumentStateError(
                "external document generation has no active sync run"
            )
        if parent_document_id is not None:
            await self._validate_parent(
                parent_document_id,
                owner_user_id=None,
                tenant_id=scope.connector.tenant_id,
                connector_scope_id=connector_scope_id,
                generation=generation,
            )

        document = await self._session.scalar(
            select(Document)
            .where(
                Document.connector_scope_id == connector_scope_id,
                Document.generation == generation,
                Document.external_id == normalized_external_id,
            )
            .with_for_update()
        )
        values: dict[str, Any] = {
            "owner_user_id": None,
            "tenant_id": scope.connector.tenant_id,
            "connector_scope_id": connector_scope_id,
            "generation": generation,
            "external_id": normalized_external_id,
            "origin": "external",
            "source_url": _optional_text(source_url),
            "external_version": _optional_text(external_version),
            "etag": _optional_text(etag),
            "external_updated_at": external_updated_at,
            "title": _optional_text(title),
            "mime_type": _optional_text(mime_type, max_length=255),
            "size_bytes": size_bytes,
            "metadata_": dict(metadata or {}),
            "raw_storage_key": _optional_text(raw_storage_key),
            "parent_document_id": parent_document_id,
            "allowed_principal_tokens": _normalize_tokens(allowed_principal_tokens),
            "denied_principal_tokens": _normalize_tokens(denied_principal_tokens),
            "indexing_status": "pending",
            "lifecycle_status": ACTIVE_STATUS,
            "last_synced_at": datetime.now(UTC),
            "deleted_at": None,
            "created_by_user_id": None,
        }
        if document is None:
            document = Document(**values)
            self._session.add(document)
        else:
            for attribute, value in values.items():
                setattr(document, attribute, value)
        await self._session.flush()
        return document

    async def replace_chunks(
        self,
        document_id: UUID,
        chunks: Sequence[DocumentChunkInput],
    ) -> list[DocumentChunk]:
        """Replace canonical chunks from a trusted ingestion worker."""

        document = await self._get_internal(document_id)
        if document.lifecycle_status == "deleted":
            raise InvalidDocumentStateError("cannot chunk a deleted document")
        if not chunks:
            raise ValueError("at least one document chunk is required")

        records = [
            _chunk_record(document_id, chunk_index, chunk)
            for chunk_index, chunk in enumerate(chunks)
        ]
        await self._session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        self._session.add_all(records)
        document.indexing_status = "pending"
        document.last_indexed_at = None
        await self._session.flush()
        return records

    async def mark_indexed(
        self,
        document_id: UUID,
        *,
        indexed_at: datetime | None = None,
    ) -> Document:
        document = await self._get_internal(document_id)
        if document.lifecycle_status == "deleted":
            raise InvalidDocumentStateError("cannot index a deleted document")
        has_chunk = await self._session.scalar(
            select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
        )
        if has_chunk is None:
            raise InvalidDocumentStateError("cannot index a document without chunks")
        document.indexing_status = "indexed"
        document.last_indexed_at = indexed_at or datetime.now(UTC)
        await self._session.flush()
        return document

    async def mark_index_failed(self, document_id: UUID) -> Document:
        document = await self._get_internal(document_id)
        if document.lifecycle_status == "deleted":
            raise InvalidDocumentStateError("cannot update a deleted document")
        document.indexing_status = "failed"
        await self._session.flush()
        return document

    async def activate_generation(
        self,
        connector_scope_id: int,
        generation: int,
        *,
        actor: AuthContext,
    ) -> ConnectorScope:
        if generation < 1:
            raise ValueError("generation must be at least one")
        if not actor.has_permissions(SOURCE_MANAGE_PERMISSION):
            raise AuthorizationError("source.manage permission is required")

        scope = await self._session.scalar(
            select(ConnectorScope)
            .options(joinedload(ConnectorScope.connector))
            .where(ConnectorScope.id == connector_scope_id)
            .with_for_update(of=ConnectorScope)
        )
        if scope is None:
            raise DocumentNotFoundError(
                f"connector scope not found: {connector_scope_id}"
            )
        if scope.status != ACTIVE_STATUS or scope.connector.status != ACTIVE_STATUS:
            raise InvalidDocumentStateError("connector scope is not active")
        if actor.tenant_id != scope.connector.tenant_id:
            raise AuthorizationError("connector scope is outside the actor's tenant")
        completed_run = await self._session.scalar(
            select(SyncRun.id).where(
                SyncRun.connector_scope_id == connector_scope_id,
                SyncRun.generation == generation,
                SyncRun.status == "completed",
            )
        )
        if completed_run is None:
            raise InvalidDocumentStateError("generation has no completed sync run")
        unready_document = await self._session.scalar(
            select(Document.id).where(
                Document.connector_scope_id == connector_scope_id,
                Document.generation == generation,
                Document.lifecycle_status.in_((ACTIVE_STATUS, "retired")),
                Document.indexing_status != "indexed",
            )
        )
        if unready_document is not None:
            raise InvalidDocumentStateError(
                "generation contains documents that are not indexed"
            )

        await self._session.execute(
            update(Document)
            .where(
                Document.connector_scope_id == connector_scope_id,
                Document.generation != generation,
                Document.lifecycle_status == ACTIVE_STATUS,
            )
            .values(lifecycle_status="retired")
        )
        await self._session.execute(
            update(Document)
            .where(
                Document.connector_scope_id == connector_scope_id,
                Document.generation == generation,
                Document.lifecycle_status.in_((ACTIVE_STATUS, "retired")),
            )
            .values(lifecycle_status=ACTIVE_STATUS)
        )
        scope.active_generation = generation
        scope.last_indexed_at = datetime.now(UTC)
        await self._session.flush()
        return scope

    async def get_document(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
        include_chunks: bool = False,
    ) -> Document:
        statement = self._visible_documents(access).where(Document.id == document_id)
        if include_chunks:
            statement = statement.options(selectinload(Document.chunks))
        document = await self._session.scalar(statement)
        if document is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        return document

    async def list_documents(
        self,
        *,
        access: AuthContext,
        connector_ids: Iterable[int] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Document]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must not be negative")

        statement = self._visible_documents(access)
        if connector_ids is not None:
            normalized_ids = sorted(set(connector_ids))
            if not normalized_ids:
                return []
            statement = statement.where(Connector.id.in_(normalized_ids))
        result = await self._session.scalars(
            statement.order_by(Document.updated_at.desc(), Document.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.unique())

    async def get_chunks(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> list[DocumentChunk]:
        await self.get_document(document_id, access=access)
        result = await self._session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return list(result)

    async def get_document_text(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> str:
        chunks = await self.get_chunks(document_id, access=access)
        return "\n\n".join(chunk.content for chunk in chunks)

    async def store_blob(self, document_id: UUID, raw_bytes: bytes) -> DocumentBlob:
        """Store raw bytes from a trusted ingestion worker."""

        await self._get_internal(document_id)
        if not raw_bytes:
            raise ValueError("raw document bytes must not be empty")
        statement = (
            insert(DocumentBlob)
            .values(document_id=document_id, raw_bytes=raw_bytes)
            .on_conflict_do_update(
                index_elements=[DocumentBlob.document_id],
                set_={"raw_bytes": raw_bytes},
            )
            .returning(DocumentBlob)
        )
        blob = await self._session.scalar(statement)
        if blob is None:
            raise InvalidDocumentStateError("document blob was not stored")
        await self._session.flush()
        return blob

    async def get_blob(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> bytes:
        await self.get_document(document_id, access=access)
        raw_bytes = await self._session.scalar(
            select(DocumentBlob.raw_bytes).where(
                DocumentBlob.document_id == document_id
            )
        )
        if raw_bytes is None:
            raise DocumentNotFoundError(f"document blob not found: {document_id}")
        return raw_bytes

    async def link_message(
        self,
        message_id: UUID,
        document_id: UUID,
        relation_type: str,
        *,
        access: AuthContext,
        position: int = 0,
    ) -> MessageDocument:
        normalized_relation = relation_type.strip().casefold()
        if normalized_relation not in MESSAGE_DOCUMENT_RELATIONS:
            raise ValueError("invalid message-document relation type")
        if position < 0:
            raise ValueError("position must not be negative")

        message_exists = await self._session.scalar(
            select(Message.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Conversation.user_id == access.user_id,
            )
        )
        if message_exists is None:
            raise DocumentNotFoundError(f"message not found: {message_id}")
        await self.get_document(document_id, access=access)

        statement = (
            insert(MessageDocument)
            .values(
                message_id=message_id,
                document_id=document_id,
                relation_type=normalized_relation,
                position=position,
            )
            .on_conflict_do_update(
                index_elements=[
                    MessageDocument.message_id,
                    MessageDocument.document_id,
                    MessageDocument.relation_type,
                ],
                set_={"position": position},
            )
            .returning(MessageDocument)
        )
        link = await self._session.scalar(statement)
        if link is None:
            raise InvalidDocumentStateError("message-document link was not stored")
        await self._session.flush()
        return link

    async def unlink_message(
        self,
        message_id: UUID,
        document_id: UUID,
        relation_type: str,
        *,
        access: AuthContext,
    ) -> None:
        message_exists = await self._session.scalar(
            select(Message.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Conversation.user_id == access.user_id,
            )
        )
        if message_exists is None:
            raise DocumentNotFoundError(f"message not found: {message_id}")
        await self._session.execute(
            delete(MessageDocument).where(
                MessageDocument.message_id == message_id,
                MessageDocument.document_id == document_id,
                MessageDocument.relation_type == relation_type.strip().casefold(),
            )
        )
        await self._session.flush()

    async def soft_delete_document(
        self,
        document_id: UUID,
        *,
        actor: AuthContext,
    ) -> Document:
        document = await self._session.get(Document, document_id)
        if document is None or document.lifecycle_status == "deleted":
            raise DocumentNotFoundError(f"document not found: {document_id}")

        owns_personal = document.owner_user_id == actor.user_id
        manages_enterprise = (
            document.tenant_id is not None
            and document.tenant_id == actor.tenant_id
            and (
                document.created_by_user_id == actor.user_id
                or actor.has_permissions(SOURCE_MANAGE_PERMISSION)
            )
        )
        if not owns_personal and not manages_enterprise:
            raise DocumentNotFoundError(f"document not found: {document_id}")

        document.lifecycle_status = "deleted"
        document.indexing_status = "none"
        document.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return document

    def _visible_documents(self, access: AuthContext) -> Select[tuple[Document]]:
        personal_access = and_(
            Document.owner_user_id == access.user_id,
            Document.tenant_id.is_(None),
        )
        access_predicate = personal_access
        if access.tenant_id is not None and access.has_permissions(
            KNOWLEDGE_READ_PERMISSION
        ):
            enterprise_access = Document.tenant_id == access.tenant_id
            if not access.is_admin:
                tokens = sorted({"public", *access.principal_tokens})
                enterprise_access = and_(
                    enterprise_access,
                    Document.allowed_principal_tokens.overlap(tokens),
                    not_(Document.denied_principal_tokens.overlap(tokens)),
                )
            access_predicate = or_(personal_access, enterprise_access)

        active_source = or_(
            Document.connector_scope_id.is_(None),
            and_(
                ConnectorScope.status == ACTIVE_STATUS,
                Connector.status == ACTIVE_STATUS,
                Document.generation == ConnectorScope.active_generation,
            ),
        )
        return (
            select(Document)
            .outerjoin(
                ConnectorScope,
                ConnectorScope.id == Document.connector_scope_id,
            )
            .outerjoin(Connector, Connector.id == ConnectorScope.connector_id)
            .where(
                Document.lifecycle_status == ACTIVE_STATUS,
                active_source,
                access_predicate,
            )
        )

    async def _get_internal(self, document_id: UUID) -> Document:
        document = await self._session.get(Document, document_id)
        if document is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        return document

    async def _active_scope(self, connector_scope_id: int) -> ConnectorScope:
        scope = await self._session.scalar(
            select(ConnectorScope)
            .options(joinedload(ConnectorScope.connector))
            .where(ConnectorScope.id == connector_scope_id)
        )
        if (
            scope is None
            or scope.status != ACTIVE_STATUS
            or scope.connector.status != ACTIVE_STATUS
        ):
            raise DocumentNotFoundError(
                f"active connector scope not found: {connector_scope_id}"
            )
        return scope

    async def _validate_parent(
        self,
        parent_document_id: UUID,
        *,
        owner_user_id: UUID | None,
        tenant_id: UUID | None,
        connector_scope_id: int | None,
        generation: int | None,
    ) -> None:
        parent = await self._get_internal(parent_document_id)
        if (
            parent.owner_user_id != owner_user_id
            or parent.tenant_id != tenant_id
            or parent.connector_scope_id != connector_scope_id
            or parent.generation != generation
        ):
            raise InvalidDocumentStateError(
                "parent document must have the same owner and source generation"
            )


def _chunk_record(
    document_id: UUID,
    chunk_index: int,
    value: DocumentChunkInput,
) -> DocumentChunk:
    content = _required_text(value.content, "chunk content")
    if value.token_count is not None and value.token_count < 0:
        raise ValueError("token count must not be negative")
    if value.start_page_number is not None and value.start_page_number < 1:
        raise ValueError("start page number must be at least one")
    if value.end_page_number is not None and value.end_page_number < 1:
        raise ValueError("end page number must be at least one")
    if (
        value.start_page_number is not None
        and value.end_page_number is not None
        and value.end_page_number < value.start_page_number
    ):
        raise ValueError("end page number must not precede start page number")
    headings = (
        [_required_text(heading, "heading") for heading in value.heading_path]
        if value.heading_path is not None
        else None
    )
    return DocumentChunk(
        document_id=document_id,
        chunk_index=chunk_index,
        content=content,
        token_count=value.token_count,
        start_page_number=value.start_page_number,
        end_page_number=value.end_page_number,
        heading_path=headings,
        metadata_=dict(value.metadata or {}),
    )


def _local_origin(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in LOCAL_DOCUMENT_ORIGINS:
        allowed = ", ".join(sorted(LOCAL_DOCUMENT_ORIGINS))
        raise ValueError(f"personal and enterprise documents require origin: {allowed}")
    return normalized


def _normalize_tokens(values: Iterable[str]) -> list[str]:
    return sorted(
        {
            _required_text(value, "principal token", max_length=512).casefold()
            for value in values
        }
    )


def _validate_size(size_bytes: int | None) -> None:
    if size_bytes is not None and size_bytes < 0:
        raise ValueError("document size must not be negative")


def _required_text(
    value: str,
    field_name: str,
    *,
    max_length: int | None = None,
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


__all__ = [
    "DocumentChunkInput",
    "DocumentNotFoundError",
    "DocumentService",
    "DocumentServiceError",
    "InvalidDocumentStateError",
]
