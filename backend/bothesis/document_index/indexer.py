"""The single indexing pipeline for uploaded and connected knowledge."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bothesis.connector.protocol import Chunk, DocumentItem
from bothesis.db.models import Item
from bothesis.document_index import (
    CHUNKER_VERSION,
    INDEX_SCHEMA_VERSION,
    PARSER_VERSION,
    ChunkContextGenerator,
    DocumentProcessingError,
    DocumentUnavailableError,
    EmbeddingService,
    IndexingContext,
    VectorIndex,
    build_contextual_chunks,
)
from bothesis.services import (
    AuthContext,
    ChatDocumentSource,
    CitationService,
    ItemService,
)


class DocumentPipeline:
    """Canonicalize when needed, then cite, embed, and replace one document."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedder: EmbeddingService,
        vector_index: VectorIndex,
        embedding_batch_size: int = 32,
        semantic_contextualizer: ChunkContextGenerator | None = None,
    ) -> None:
        if embedding_batch_size < 1:
            raise ValueError("embedding_batch_size must be at least one")
        self._session_factory = session_factory
        self._embedder = embedder
        self._vector_index = vector_index
        self._embedding_batch_size = embedding_batch_size
        self._semantic_contextualizer = semantic_contextualizer

    async def index_upload(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
        source: ChatDocumentSource,
    ) -> Item:
        """Canonicalize and index an available upload under a retry-safe lock."""

        engine = self._session_factory.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise RuntimeError("document pipeline requires an AsyncEngine-bound session")
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

    async def index_document(
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

            contextual_chunks = await build_contextual_chunks(
                chunks,
                item,
                semantic_contextualizer=self._semantic_contextualizer,
            )
            async with self._session_factory.begin() as session:
                await CitationService(session).replace_for_item(stored.id, chunks)

            vectors: list[list[float]] = []
            texts = [chunk.contextual_text for chunk in contextual_chunks]
            for start in range(0, len(texts), self._embedding_batch_size):
                vectors.extend(
                    await self._embedder.embed_documents(
                        texts[start : start + self._embedding_batch_size]
                    )
                )
            if len(vectors) != len(contextual_chunks) or any(
                not vector for vector in vectors
            ):
                raise ValueError("every contextual chunk requires one embedding")

            await self._vector_index.replace_document(
                stored,
                contextual_chunks,
                vectors,
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
            return len(contextual_chunks)
        except Exception:
            async with self._session_factory.begin() as session:
                await ItemService(session).mark_failed(stored.id)
            raise

    async def delete_upload(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> None:
        """Tombstone an upload and all of its derived index records."""

        if access.tenant_id is None:
            raise DocumentUnavailableError("an active tenant is required")
        engine = self._session_factory.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise RuntimeError("document pipeline requires an AsyncEngine-bound session")
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

                await self._vector_index.soft_delete_document(
                    document_id,
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

    async def aclose(self) -> None:
        for dependency in (self._embedder, self._vector_index):
            close = getattr(dependency, "aclose", None)
            if close is not None:
                await close()

    async def _index_upload_under_lock(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
        source: ChatDocumentSource,
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

        await self.index_document(
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
        return (
            document.status == "ready"
            and processing.get("provider_version") == self._provider_version(document)
            and processing.get("parser_version") == PARSER_VERSION
            and processing.get("chunker_version") == CHUNKER_VERSION
            and processing.get("embedding_model") == self._embedder.embedding_model
            and processing.get("index_schema_version") == INDEX_SCHEMA_VERSION
            and processing.get("contextualization_enabled")
            is (self._semantic_contextualizer is not None)
            and processing.get("contextualization_model")
            == (
                self._semantic_contextualizer.model_name
                if self._semantic_contextualizer is not None
                else None
            )
        )

    def _upload_processing_metadata(self, document: Item) -> dict[str, Any]:
        return {
            "provider_version": self._provider_version(document),
            "parser_version": PARSER_VERSION,
            "chunker_version": CHUNKER_VERSION,
            "embedding_model": self._embedder.embedding_model,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "contextualization_enabled": self._semantic_contextualizer is not None,
            "contextualization_model": (
                self._semantic_contextualizer.model_name
                if self._semantic_contextualizer is not None
                else None
            ),
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

    @staticmethod
    def _advisory_lock_key(document_id: UUID) -> int:
        return int.from_bytes(document_id.bytes[:8], byteorder="big", signed=True)


__all__ = ["DocumentPipeline"]
