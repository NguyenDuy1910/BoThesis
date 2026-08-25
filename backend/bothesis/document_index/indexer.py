"""Reusable single-document processing pipeline outside the agent loop."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bothesis.connector.protocol import (
    CitationInfo,
    EffectiveAccess,
    Hierarchy,
    ProviderCacheEntry,
    ProviderFileCache,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index import (
    CHUNKER_VERSION,
    DEFAULT_DIRECT_MAX_BYTES,
    DIRECT_IMAGE_TYPES,
    INDEX_SCHEMA_VERSION,
    PARSER_VERSION,
    DocumentProcessingError,
    DocumentUnavailableError,
    PreparedDocuments,
    VectorIndex,
)
from bothesis.document_index.embedding import EmbeddingService, embedding_texts
from bothesis.document_index.models import ContextualChunk, PreparedDocument
from bothesis.document_index.payload import build_contextual_chunks
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer
from bothesis.db.models import Item
from bothesis.services import (
    AuthContext,
    ChatDocumentSource,
    DEFAULT_PROCESSING_MAX_BYTES,
    ItemService,
)

log = logging.getLogger(__name__)

class DocumentPipeline:
    """Process Documents through Direct or retrieval paths.

    Chat uploads, external upload adapters, and future connectors can reuse
    this pipeline without coupling document processing to the agent loop.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        document_source: ChatDocumentSource,
        embedder: EmbeddingService,
        vector_index: VectorIndex,
        provider_cache: ProviderFileCache,
        direct_max_bytes: int = DEFAULT_DIRECT_MAX_BYTES,
        retrieval_limit: int = 6,
        embedding_batch_size: int = 32,
        download_url_seconds: int = 300,
        semantic_contextualizer: SemanticContextualizer | None = None,
    ) -> None:
        if (
            min(
                direct_max_bytes,
                retrieval_limit,
                embedding_batch_size,
                download_url_seconds,
            )
            < 1
        ):
            raise ValueError("document processing limits must be greater than zero")
        self._session_factory = session_factory
        self._document_source = document_source
        self._embedder = embedder
        self._vector_index = vector_index
        self._provider_cache = provider_cache
        self._direct_max_bytes = direct_max_bytes
        self._retrieval_limit = retrieval_limit
        self._embedding_batch_size = embedding_batch_size
        self._download_url_seconds = download_url_seconds
        self._semantic_contextualizer = semantic_contextualizer

    async def prepare_for_message(
        self,
        document_ids: Sequence[UUID],
        *,
        access: AuthContext,
        message: str,
    ) -> PreparedDocuments:
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("document IDs must be unique")
        contexts: list[PreparedDocument] = []
        for document_id in document_ids:
            document = await self._load_visible_document(document_id, access=access)
            mode = self._route(document)
            try:
                if mode == "direct":
                    context = await self._prepare_direct(document)
                else:
                    context = await self._prepare_indexed(
                        document,
                        access=access,
                        message=message,
                    )
            except Exception:
                raise
            contexts.append(context)
        return PreparedDocuments(tuple(contexts))

    async def cache_provider_annotations(
        self,
        prepared: PreparedDocuments,
        annotations: Sequence[Mapping[str, Any]],
    ) -> None:
        file_annotations = [
            dict(annotation)
            for annotation in annotations
            if annotation.get("type") == "file"
            and isinstance(annotation.get("file"), Mapping)
        ]
        if not file_annotations:
            return
        direct_documents = [
            context
            for context in prepared.contexts
            if context.mode == "direct" and context.content_type == "application/pdf"
        ]
        remaining = list(file_annotations)
        for position, context in enumerate(direct_documents):
            match_index = next(
                (
                    index
                    for index, annotation in enumerate(remaining)
                    if _annotation_name(annotation) == context.title
                ),
                None,
            )
            if (
                match_index is None
                and len(remaining) == len(direct_documents) - position
            ):
                match_index = 0
            if match_index is None:
                continue
            annotation = remaining.pop(match_index)
            document_id = UUID(context.id)
            async with self._session_factory() as session:
                document = await session.get(Item, document_id)
            if document is None:
                continue
            provider_version = _provider_version(document)
            try:
                await self._provider_cache.put(
                    document_id,
                    ProviderCacheEntry(
                        provider="openrouter",
                        provider_version=provider_version,
                        reference={"annotations": [annotation]},
                    ),
                )
            except ValueError:
                log.warning(
                    "provider annotation cache exceeded its limit document_id=%s",
                    document_id,
                )

    async def index_document(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> Item:
        """Parse and index an available native upload with retry-safe locking."""

        return await self._ensure_indexed(document_id, access=access)

    async def soft_delete_document(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> None:
        engine = self._session_factory.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise RuntimeError(
                "document processor requires an AsyncEngine-bound session"
            )
        lock_key = _advisory_lock_key(document_id)
        async with engine.connect() as connection:
            await connection.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            try:
                await self._soft_delete_under_lock(document_id, access=access)
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

    async def _soft_delete_under_lock(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> None:
        has_derived_index = False
        async with self._session_factory.begin() as session:
            if access.tenant_id is None:
                raise DocumentUnavailableError("an active tenant is required")
            document = await ItemService(session).get_owned_upload(
                document_id,
                access.user_id,
                access.tenant_id,
                include_deleted=True,
            )
            if document.status == "deleted":
                return
            has_derived_index = isinstance(document.metadata_.get("processing"), Mapping)
            document.status = "processing"

        if has_derived_index:
            await self._vector_index.soft_delete_document(document_id)
        await self._provider_cache.clear(document_id)

        async with self._session_factory.begin() as session:
            if access.tenant_id is None:
                raise DocumentUnavailableError("an active tenant is required")
            items = ItemService(session)
            await items.get_owned_upload(
                document_id,
                access.user_id,
                access.tenant_id,
                include_deleted=True,
            )
            await items.soft_delete_item(document_id, actor=access)

    async def _load_visible_document(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> Item:
        if access.tenant_id is None:
            raise DocumentUnavailableError("an active tenant is required")
        async with self._session_factory() as session:
            document = await ItemService(session).get_upload_for_access(
                document_id,
                access,
            )
            assert document.upload is not None
            if document.upload.status != "available":
                raise DocumentUnavailableError("document content is not available")
            return document

    def _route(self, document: Item) -> str:
        content_type = (document.mime_type or "").casefold()
        within_direct_limit = (document.size_bytes or 0) <= self._direct_max_bytes
        if content_type in DIRECT_IMAGE_TYPES and within_direct_limit:
            return "direct"
        if self._index_content_is_current(document):
            return "indexed"
        if content_type == "application/pdf" and within_direct_limit:
            return "direct"
        return "indexed"

    def _index_is_current(self, document: Item, *, access: AuthContext) -> bool:
        processing = document.metadata_.get("processing")
        return (
            self._index_content_is_current(document)
            and isinstance(processing, Mapping)
            and processing.get("tenant_id") == str(access.tenant_id)
            and processing.get("owner_user_id") == str(access.user_id)
        )

    def _index_content_is_current(self, document: Item) -> bool:
        processing = document.metadata_.get("processing")
        if not isinstance(processing, Mapping):
            return False
        return (
            document.status == "ready"
            and processing.get("provider_version") == _provider_version(document)
            and processing.get("parser_version") == PARSER_VERSION
            and processing.get("chunker_version") == CHUNKER_VERSION
            and processing.get("embedding_model") == self._embedder.model
            and processing.get("index_schema_version") == INDEX_SCHEMA_VERSION
        )

    async def _prepare_direct(
        self,
        document: Item,
    ) -> PreparedDocument:
        provider_version = _provider_version(document)
        cached = await self._provider_cache.get(
            document.id,
            provider="openrouter",
            provider_version=provider_version,
        )
        annotations: tuple[Mapping[str, Any], ...] = ()
        if cached is not None:
            raw_annotations = cached.reference.get("annotations")
            if isinstance(raw_annotations, list):
                annotations = tuple(
                    annotation
                    for annotation in raw_annotations
                    if isinstance(annotation, Mapping)
                )

        content_type = document.mime_type or "application/octet-stream"
        file_data: str | None = None
        if not annotations:
            file_data = await self._document_source.direct_file_data(
                document,
                expires_seconds=self._download_url_seconds,
            )

        evidence_id = f"document:{document.id}"
        content_block: Mapping[str, Any] | None = None
        if file_data is not None:
            if content_type in DIRECT_IMAGE_TYPES:
                content_block = {
                    "type": "image_url",
                    "image_url": {"url": file_data},
                }
            elif content_type == "application/pdf":
                content_block = {
                    "type": "file",
                    "file": {
                        "filename": _file_name(document),
                        "file_data": file_data,
                    },
                }
            else:
                raise DocumentProcessingError("document type is not direct-capable")
        return PreparedDocument(
                id=str(document.id),
                title=_file_name(document),
                content_type=content_type,
                mode="direct",
                citation_id=evidence_id,
                content_block=content_block,
                chunks=(
                    ContextualChunk(
                        id=evidence_id,
                        item_id=str(document.id),
                        chunk_index=0,
                        content_type=content_type,
                        chunk_text="Original user-supplied document provided directly to the model.",
                        contextual_text="Original user-supplied document provided directly to the model.",
                        title=_file_name(document),
                        document_type=document.document_type or "plain_text",
                        collection_item_id=(
                            str(document.parent_item_id)
                            if document.parent_item_id is not None
                            else None
                        ),
                        source=SourceIdentity(
                            connector_id="upload",
                            provider=SourceProvider.FILE,
                            external_id=str(document.id),
                            url=None,
                        ),
                        hierarchy=Hierarchy(),
                        access=EffectiveAccess(),
                        citation=CitationInfo(),
                    ),
                ),
                provider_annotations=annotations,
            )

    async def _prepare_indexed(
        self,
        document: Item,
        *,
        access: AuthContext,
        message: str,
    ) -> PreparedDocument:
        document = await self._ensure_indexed(document.id, access=access)
        query_vector = await self._embedder.embed_query(message)
        chunks = await self._vector_index.search_document(
            document,
            message,
            query_vector,
            access=access,
            limit=self._retrieval_limit,
        )
        return PreparedDocument(
                id=str(document.id),
                title=_file_name(document),
                content_type=document.mime_type or "application/octet-stream",
                mode="indexed",
                citation_id=f"document:{document.id}",
                chunks=chunks,
            )

    async def _ensure_indexed(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> Item:
        engine = self._session_factory.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise RuntimeError(
                "document processor requires an AsyncEngine-bound session"
            )
        lock_key = _advisory_lock_key(document_id)
        async with engine.connect() as connection:
            await connection.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            try:
                return await self._index_under_lock(document_id, access=access)
            finally:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )

    async def _index_under_lock(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> Item:
        async with self._session_factory() as session:
            if access.tenant_id is None:
                raise DocumentUnavailableError("an active tenant is required")
            items = ItemService(session)
            document = await items.get_upload_for_access(
                document_id,
                access,
                minimum_role="editor",
            )
            if self._index_is_current(document, access=access):
                return document
            if self._index_content_is_current(document):
                await self._vector_index.update_document_access(
                    document.id,
                    access=access,
                )
                async with self._session_factory.begin() as update_session:
                    items = ItemService(update_session)
                    processing = dict(document.metadata_.get("processing") or {})
                    processing.update(
                        {
                            "tenant_id": str(access.tenant_id),
                            "owner_user_id": str(access.user_id),
                        }
                    )
                    return await items.merge_metadata(
                        document.id,
                        {"processing": processing},
                    )

        try:
            async with self._session_factory.begin() as session:
                await ItemService(session).mark_processing(document.id)
            canonical = await self._document_source.canonicalize(
                document, access=access
            )
            canonical_item = canonical.item
            canonical_chunks = canonical.chunks

            contextual_chunks = await build_contextual_chunks(
                canonical_chunks,
                canonical_item,
                semantic_contextualizer=self._semantic_contextualizer,
            )
            vectors: list[list[float]] = []
            for start in range(0, len(contextual_chunks), self._embedding_batch_size):
                batch = contextual_chunks[start : start + self._embedding_batch_size]
                vectors.extend(
                    await self._embedder.embed_documents(embedding_texts(batch))
                )
            await self._vector_index.replace_document(
                document,
                contextual_chunks,
                vectors,
                access=access,
                embedding_model=self._embedder.model,
            )
            async with self._session_factory.begin() as session:
                items = ItemService(session)
                await items.merge_metadata(
                    document.id,
                    {
                        "processing": {
                            "provider_version": _provider_version(document),
                            "parser_version": PARSER_VERSION,
                            "chunker_version": CHUNKER_VERSION,
                            "embedding_model": self._embedder.model,
                            "index_schema_version": INDEX_SCHEMA_VERSION,
                            "tenant_id": str(access.tenant_id),
                            "owner_user_id": str(access.user_id),
                        }
                    },
                )
                return await items.mark_ready(document.id)
        except Exception as exc:
            async with self._session_factory.begin() as session:
                await ItemService(session).mark_failed(document.id)
            if isinstance(exc, DocumentProcessingError):
                raise
            raise DocumentProcessingError("document indexing failed") from exc


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
    return f"native:{document.id}:{updated_at.isoformat() if updated_at else 'initial'}"


def _advisory_lock_key(document_id: UUID) -> int:
    return int.from_bytes(document_id.bytes[:8], byteorder="big", signed=True)


def _file_name(document: Item) -> str:
    value = document.metadata_.get("file_name") or document.title or str(document.id)
    return str(value)


def _annotation_name(annotation: Mapping[str, Any]) -> str | None:
    file_value = annotation.get("file")
    if not isinstance(file_value, Mapping):
        return None
    name = file_value.get("name")
    return name if isinstance(name, str) else None


__all__ = [
    "CHUNKER_VERSION",
    "DEFAULT_DIRECT_MAX_BYTES",
    "DEFAULT_PROCESSING_MAX_BYTES",
    "DocumentProcessingError",
    "DocumentPipeline",
    "DocumentUnavailableError",
    "EmbeddingService",
    "PARSER_VERSION",
    "PreparedDocuments",
    "VectorIndex",
]
