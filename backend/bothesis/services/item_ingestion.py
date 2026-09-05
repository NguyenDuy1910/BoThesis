"""The application service that ingests, refreshes, and removes Item content."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from bothesis.connector.protocol import (
    AnyItem,
    Chunk,
    CollectionItem,
    DocumentItem,
    DocumentKind,
)
from bothesis.db.models import ExternalResource, IngestionSource, Item
from bothesis.document_index import IndexingContext, ItemIndex
from bothesis.services.citation import CitationService
from bothesis.services.item import ItemService
from bothesis.services import (
    CHUNKER_VERSION,
    PARSER_VERSION,
    AuthContext,
    StoredFileContent,
    DocumentProcessingError,
    DocumentUnavailableError,
)
from bothesis.services.preview import KnowledgePreview

log = logging.getLogger(__name__)


class ItemIngestionService:
    """Ingest, refresh, and remove Item content for uploads and connectors.

    Owns Item status transitions and citation persistence around indexing;
    the actual indexing/search/removal work is delegated to the injected
    ItemIndex. Implements ConnectorIndexSink (write_item/write/soft_delete_item)
    directly so it can be handed straight to a ConnectorPipeline as its sink.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        index: ItemIndex,
        ingestion_source_id: UUID | None = None,
        preview: KnowledgePreview | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._index = index
        self._ingestion_source_id = ingestion_source_id
        self._preview = preview

    # ---- Upload-facing ----

    async def index_upload(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
        source: StoredFileContent,
    ) -> Item:
        """Canonicalize and index an available upload under a retry-safe lock."""

        engine = self._require_engine()
        lock_key = self._advisory_lock_key(document_id)
        async with engine.connect() as connection:
            await connection.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            try:
                return await self._index_upload_under_lock(
                    document_id,
                    access=access,
                    source=source,
                )
            finally:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )

    async def remove_upload(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> None:
        """Tombstone an upload and all of its derived index records."""

        if access.tenant_id is None:
            raise DocumentUnavailableError("an active tenant is required")
        engine = self._require_engine()
        lock_key = self._advisory_lock_key(document_id)
        async with engine.connect() as connection:
            await connection.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            try:
                async with self._session_factory.begin() as session:
                    items = ItemService(session)
                    document = await items.get_owned_upload(
                        document_id,
                        access.user_id,
                        access.tenant_id,
                        include_deleted=True,
                    )
                    if document.status == "deleted":
                        return
                    document.status = "processing"

                await self._index.remove_item_content(
                    str(document_id),
                    tenant_id=str(access.tenant_id),
                )
                async with self._session_factory.begin() as session:
                    items = ItemService(session)
                    await CitationService(session).replace_for_item(document_id, ())
                    await items.soft_delete_item(document_id, actor=access)
            finally:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )

    async def remove_item(self, item_id: UUID, *, actor: AuthContext) -> None:
        """Tombstone an authorized Item and all of its derived content."""

        if actor.tenant_id is None:
            raise DocumentUnavailableError("an active tenant is required")
        async with self._session_factory.begin() as session:
            items = ItemService(session)
            item = await items.get_item(item_id, access=actor)
            if item.status == "deleted":
                return
            item.status = "processing"
        await self._index.remove_item_content(
            str(item_id),
            tenant_id=str(actor.tenant_id),
        )
        async with self._session_factory.begin() as session:
            await CitationService(session).replace_for_item(item_id, ())
            await ItemService(session).soft_delete_item(item_id, actor=actor)

    # ---- Connector-facing (ConnectorIndexSink) ----

    async def write_item(
        self,
        item: AnyItem,
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> UUID:
        self._validate_source(
            item,
            tenant_id=tenant_id,
            integration_connection_id=connector_id,
        )
        stored, _, _ = await self._persist_item(item)
        return stored.id

    async def write(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> int:
        normalized_tenant = self._validate_source(
            item, tenant_id=tenant_id, integration_connection_id=connector_id
        )
        stored, source, _ = await self._persist_item(item, status="processing")
        await self._persist_preview(stored)
        canonical_item, canonical_chunks = self._canonical_document(
            item,
            chunks,
            stored,
        )
        return await self.process_item_content(
            stored,
            canonical_item,
            canonical_chunks,
            context=IndexingContext(
                tenant_id=normalized_tenant,
                collection_item_id=str(source.target_item_id),
                parent_item_id=(
                    str(stored.parent_item_id) if stored.parent_item_id else None
                ),
                document_type=stored.document_type or "plain_text",
                connector_key=source.integration_connection.connector_key,
            ),
        )

    async def soft_delete_item(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        item_id: str,
    ) -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be blank")
        async with self._session_factory.begin() as session:
            source = await session.scalar(
                select(IngestionSource)
                .options(joinedload(IngestionSource.integration_connection))
                .where(IngestionSource.id == self._ingestion_source_id)
            )
            if source is None or str(source.integration_connection_id) != str(
                connector_id
            ):
                raise ValueError(
                    "ingestion source connection does not match the delete request"
                )
            stored = await ItemService(session).soft_delete_external_resource(
                source.id,
                item_id,
            )
            canonical_id = stored.id if stored is not None else None
            if canonical_id is not None:
                await CitationService(session).replace_for_item(canonical_id, ())
        if canonical_id is not None:
            await self._index.remove_item_content(
                str(canonical_id),
                tenant_id=tenant_id.strip(),
            )

    # ---- Shared core ----

    async def process_item_content(
        self,
        stored: Item,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        context: IndexingContext,
        processing_metadata: Mapping[str, Any] | None = None,
    ) -> int:
        """Index canonical connector output through the source-neutral path."""

        try:
            async with self._session_factory.begin() as session:
                await ItemService(session).mark_processing(stored.id)
            if item.id != str(stored.id):
                raise ValueError("canonical item does not match the stored document")
            if any(chunk.item_id != item.id for chunk in chunks):
                raise ValueError("canonical chunk belongs to a different document")

            async with self._session_factory.begin() as session:
                await CitationService(session).replace_for_item(stored.id, chunks)

            count = await self._index.index_item_content(
                item,
                chunks,
                context=context,
            )

            async with self._session_factory.begin() as session:
                items = ItemService(session)
                if processing_metadata is not None:
                    await items.merge_metadata(
                        stored.id,
                        {"processing": dict(processing_metadata)},
                    )
                await items.mark_ready(stored.id)
            return count
        except Exception:
            async with self._session_factory.begin() as session:
                await ItemService(session).mark_failed(stored.id)
            raise

    async def aclose(self) -> None:
        await self._index.aclose()

    # ---- Upload-flow internals ----

    async def _index_upload_under_lock(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
        source: StoredFileContent,
    ) -> Item:
        document = await self._load_upload(
            document_id,
            access=access,
            minimum_role="editor",
        )
        if self._index_is_current(document):
            return document
        try:
            canonical = await source.canonicalize(document, access=access)
            assert access.tenant_id is not None
        except Exception as exc:
            async with self._session_factory.begin() as session:
                await ItemService(session).mark_failed(document.id)
            if isinstance(exc, DocumentProcessingError):
                raise
            raise DocumentProcessingError("document canonicalization failed") from exc

        await self._persist_preview(document)
        await self.process_item_content(
            document,
            canonical.item,
            canonical.chunks,
            context=IndexingContext(
                tenant_id=str(access.tenant_id),
                collection_item_id=str(document.parent_item_id),
                parent_item_id=str(document.parent_item_id),
                document_type=document.document_type or "plain_text",
                connector_key="file",
            ),
            processing_metadata=self._upload_processing_metadata(document),
        )
        return await self._load_upload(document.id, access=access)

    async def _load_upload(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
        minimum_role: str = "viewer",
    ) -> Item:
        if access.tenant_id is None:
            raise DocumentUnavailableError("an active tenant is required")
        async with self._session_factory() as session:
            document = await ItemService(session).get_upload_for_access(
                document_id,
                access,
                minimum_role=minimum_role,
            )
            assert document.upload is not None
            if document.upload.status != "available":
                raise DocumentUnavailableError("document content is not available")
            return document

    def _index_is_current(self, document: Item) -> bool:
        processing = document.metadata_.get("processing")
        if not isinstance(processing, Mapping):
            return False
        signature = self._index.current_processing_signature()
        return (
            document.status == "ready"
            and processing.get("provider_version") == self._provider_version(document)
            and processing.get("parser_version") == PARSER_VERSION
            and processing.get("chunker_version") == CHUNKER_VERSION
            and processing.get("embedding_model") == signature["embedding_model"]
            and processing.get("index_schema_version")
            == signature["index_schema_version"]
            and processing.get("contextualization_enabled")
            == signature["contextualization_enabled"]
            and processing.get("contextualization_model")
            == signature["contextualization_model"]
        )

    def _upload_processing_metadata(self, document: Item) -> dict[str, Any]:
        return {
            "provider_version": self._provider_version(document),
            "parser_version": PARSER_VERSION,
            "chunker_version": CHUNKER_VERSION,
            **self._index.current_processing_signature(),
        }

    @staticmethod
    def _provider_version(document: Item) -> str:
        metadata = document.metadata_
        for key in ("provider_version", "version_id", "etag"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                return value
        storage = metadata.get("storage")
        if isinstance(storage, Mapping):
            for key in ("provider_version", "version_id", "etag"):
                value = storage.get(key)
                if isinstance(value, str) and value:
                    return value
        updated_at = getattr(document, "updated_at", None)
        timestamp = updated_at.isoformat() if updated_at else "initial"
        return f"native:{document.id}:{timestamp}"

    def _require_engine(self) -> AsyncEngine:
        engine = self._session_factory.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise RuntimeError(  # noqa: TRY004 - invalid service composition
                "ItemIngestionService requires an AsyncEngine-bound session"
            )
        return engine

    @staticmethod
    def _advisory_lock_key(document_id: UUID) -> int:
        return int.from_bytes(document_id.bytes[:8], byteorder="big", signed=True)

    # ---- Connector-flow internals ----

    async def _persist_item(
        self, item: AnyItem, *, status: str | None = None
    ) -> tuple[Item, IngestionSource, ExternalResource]:
        original = item.original if isinstance(item, DocumentItem) else None
        metadata = {
            **{
                key: value
                for key, value in item.metadata.items()
                if key not in {"preview", "processing", "storage"}
            },
            "source": item.source.model_dump(mode="json", exclude_none=True),
            "external_hierarchy": item.hierarchy.model_dump(
                mode="json", exclude_none=True
            ),
        }
        if original is not None:
            metadata["storage"] = original.model_dump(mode="json", exclude_none=True)
        async with self._session_factory.begin() as session:
            source = await session.scalar(
                select(IngestionSource)
                .options(
                    joinedload(IngestionSource.integration_connection),
                    joinedload(IngestionSource.target_item),
                )
                .where(IngestionSource.id == self._ingestion_source_id)
            )
            if source is None:
                raise ValueError(
                    f"ingestion source not found: {self._ingestion_source_id}"
                )
            stored = await ItemService(session).upsert_ingested_item(
                source.id,
                item.source.external_id,
                canonical_external_id=item.id,
                item_type=item.type,
                title=item.title,
                document_type=(
                    self._document_type(
                        item, source.integration_connection.connector_key
                    )
                    if isinstance(item, DocumentItem)
                    else None
                ),
                parent_external_id=item.hierarchy.parent_id,
                parent_relation=self._parent_relation(item),
                source_url=item.source.url,
                external_version=item.source.external_version,
                etag=item.source.etag,
                external_updated_at=item.updated_at,
                mime_type=(
                    original.content_type
                    if original is not None
                    else self._mime_type(item)
                ),
                size_bytes=original.size_bytes if original is not None else None,
                metadata=metadata,
                storage_key=original.key if original is not None else None,
                status=status or "ready",
            )
            external_resource = await session.scalar(
                select(ExternalResource).where(
                    ExternalResource.ingestion_source_id == source.id,
                    ExternalResource.external_id == item.source.external_id,
                )
            )
            if external_resource is None:
                raise RuntimeError("external resource was not stored")
            session.expunge(stored)
            session.expunge(source)
            session.expunge(external_resource)
            return stored, source, external_resource

    async def _persist_preview(self, stored: Item) -> None:
        if self._preview is None or not stored.storage_key:
            return
        try:
            manifest = await self._preview.generate(stored)
            if manifest is None:
                return
            preview_metadata = manifest.model_dump(mode="json")
            if stored.metadata_.get("preview") == preview_metadata:
                return
            async with self._session_factory.begin() as session:
                await ItemService(session).merge_metadata(
                    stored.id,
                    {"preview": preview_metadata},
                )
            stored.metadata_ = {
                **dict(stored.metadata_),
                "preview": preview_metadata,
            }
        except Exception as exc:  # noqa: BLE001 - preview is best effort
            log.warning(
                "item preview generation failed item_id=%s error_type=%s",
                stored.id,
                type(exc).__name__,
            )

    @staticmethod
    def _canonical_document(
        item: DocumentItem, chunks: Sequence[Chunk], stored: Item
    ) -> tuple[DocumentItem, tuple[Chunk, ...]]:
        canonical_id = str(stored.id)
        hierarchy = item.hierarchy.model_copy(
            update={
                "parent_id": str(stored.parent_item_id)
                if stored.parent_item_id
                else None,
                "root_id": None,
                "ancestor_ids": [],
            }
        )
        canonical_item = item.model_copy(
            update={"id": canonical_id, "hierarchy": hierarchy}
        )
        canonical_chunks = tuple(
            chunk.model_copy(
                update={
                    "id": f"{canonical_id}:{chunk.chunk_index}",
                    "item_id": canonical_id,
                }
            )
            for chunk in chunks
        )
        return canonical_item, canonical_chunks

    @staticmethod
    def _validate_source(
        item: AnyItem, *, tenant_id: str, integration_connection_id: str | int
    ) -> str:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be blank")
        if str(item.source.connector_id) != str(integration_connection_id):
            raise ValueError(
                "item source integration connection does not match the index request"
            )
        return normalized_tenant

    @staticmethod
    def _document_type(item: DocumentItem, connector_key: str) -> str:
        if item.document_kind == DocumentKind.PAGE:
            return "confluence_page" if connector_key == "confluence" else "web_page"
        return {
            DocumentKind.PDF: "pdf",
            DocumentKind.DOCUMENT: "word_document",
            DocumentKind.IMAGE: "image",
            DocumentKind.ISSUE: "jira_issue",
            DocumentKind.MESSAGE: "plain_text",
            DocumentKind.EMAIL: "email",
            DocumentKind.NOTE: "plain_text",
            DocumentKind.WEB_PAGE: "web_page",
            DocumentKind.RECORD: "plain_text",
        }.get(item.document_kind, "plain_text")

    @staticmethod
    def _mime_type(item: DocumentItem) -> str | None:
        if item.document_kind == DocumentKind.PDF:
            return "application/pdf"
        if item.document_kind == DocumentKind.IMAGE:
            return "image/*"
        if item.document_kind in {DocumentKind.PAGE, DocumentKind.WEB_PAGE}:
            return "text/html"
        return None

    @staticmethod
    def _parent_relation(item: AnyItem) -> str:
        relation = item.metadata.get("parent_relation")
        if isinstance(relation, str) and relation in {
            "contains",
            "child",
            "attachment",
            "embedded",
        }:
            return relation
        if isinstance(item, CollectionItem):
            return "contains"
        if item.metadata.get("attachment_id") or item.metadata.get("file_name"):
            return "attachment"
        return "child"


__all__ = ["ItemIngestionService"]
