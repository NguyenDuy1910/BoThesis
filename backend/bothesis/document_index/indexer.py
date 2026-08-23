"""Reusable single-document processing pipeline outside the agent loop."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bothesis.connector.protocol import (
    AccessPolicy,
    Chunk,
    CitationInfo,
    CitationSpan,
    DocumentItem,
    DocumentKind,
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
    PARSER_VERSION,
    DocumentProcessingError,
    DocumentUnavailableError,
    PreparedDocuments,
    VectorIndex,
)
from bothesis.document_index.contextualization import StructuralContextualizer
from bothesis.document_index.embedding import EmbeddingService, embedding_texts
from bothesis.document_index.models import ContextualChunk, PreparedDocument
from bothesis.db.models import Document, DocumentChunk
from bothesis.services import (
    AuthContext,
    ChatDocumentSource,
    DEFAULT_PROCESSING_MAX_BYTES,
    DocumentChunkInput,
    DocumentService,
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
        fingerprints: dict[UUID, str] = {}
        for document_id in document_ids:
            document = await self._load_visible_document(document_id, access=access)
            title = _file_name(document)
            mode = self._route(document)
            try:
                if mode == "direct":
                    context, fingerprint = await self._prepare_direct(document)
                else:
                    context, fingerprint = await self._prepare_indexed(
                        document,
                        access=access,
                        message=message,
                    )
            except Exception:
                raise
            contexts.append(context)
            fingerprints[document.id] = fingerprint
        return PreparedDocuments(tuple(contexts), fingerprints)

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
            fingerprint = prepared.source_fingerprints.get(document_id)
            if not fingerprint:
                continue
            try:
                await self._provider_cache.put(
                    document_id,
                    ProviderCacheEntry(
                        provider="openrouter",
                        source_fingerprint=fingerprint,
                        reference={"annotations": [annotation]},
                    ),
                )
            except ValueError:
                log.warning(
                    "provider annotation cache exceeded its limit document_id=%s",
                    document_id,
                )

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
            document = await DocumentService(session).get_owned_upload(
                document_id,
                access.user_id,
                include_hidden=True,
            )
            if document.lifecycle_status == "deleted":
                return
            document.lifecycle_status = "hidden"
            has_derived_index = document.indexing_status != "none"

        if has_derived_index:
            await self._vector_index.soft_delete_document(document_id)
        await self._provider_cache.clear(document_id)

        async with self._session_factory.begin() as session:
            documents = DocumentService(session)
            await documents.get_owned_upload(
                document_id,
                access.user_id,
                include_hidden=True,
            )
            await self._document_source.soft_delete_raw(
                document_id,
                session=session,
            )
            await documents.soft_delete_document(document_id, actor=access)

    async def _load_visible_document(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> Document:
        async with self._session_factory() as session:
            document = await DocumentService(session).get_document(
                document_id,
                access=access,
            )
            if document.origin != "upload" or document.upload_status != "available":
                raise DocumentUnavailableError("document content is not available")
            return document

    def _route(self, document: Document) -> str:
        content_type = (document.mime_type or "").casefold()
        within_direct_limit = (document.size_bytes or 0) <= self._direct_max_bytes
        if content_type in DIRECT_IMAGE_TYPES and within_direct_limit:
            return "direct"
        if self._index_content_is_current(document):
            return "indexed"
        if content_type == "application/pdf" and within_direct_limit:
            return "direct"
        return "indexed"

    def _index_is_current(self, document: Document, *, access: AuthContext) -> bool:
        processing = document.metadata_.get("processing")
        return (
            self._index_content_is_current(document)
            and isinstance(processing, Mapping)
            and processing.get("tenant_id") == str(access.tenant_id)
            and processing.get("owner_user_id") == str(access.user_id)
        )

    def _index_content_is_current(self, document: Document) -> bool:
        processing = document.metadata_.get("processing")
        if not isinstance(processing, Mapping):
            return False
        return (
            document.indexing_status == "indexed"
            and processing.get("source_fingerprint") == _source_fingerprint(document)
            and processing.get("parser_version") == PARSER_VERSION
            and processing.get("chunker_version") == CHUNKER_VERSION
            and processing.get("embedding_model") == self._embedder.model
        )

    async def _prepare_direct(
        self,
        document: Document,
    ) -> tuple[PreparedDocument, str]:
        fingerprint = _source_fingerprint(document)
        cached = await self._provider_cache.get(
            document.id,
            provider="openrouter",
            source_fingerprint=fingerprint,
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
        return (
            PreparedDocument(
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
                        document_kind="document",
                        source=SourceIdentity(
                            connector_id="upload",
                            provider=SourceProvider.FILE,
                            external_id=str(document.id),
                            url=document.source_url,
                        ),
                        hierarchy=Hierarchy(),
                        access=EffectiveAccess(),
                        citation=CitationInfo(),
                    ),
                ),
                provider_annotations=annotations,
            ),
            fingerprint,
        )

    async def _prepare_indexed(
        self,
        document: Document,
        *,
        access: AuthContext,
        message: str,
    ) -> tuple[PreparedDocument, str]:
        document = await self._ensure_indexed(document.id, access=access)
        query_vector = await self._embedder.embed_query(message)
        chunks = await self._vector_index.search_document(
            document,
            query_vector,
            access=access,
            limit=self._retrieval_limit,
        )
        return (
            PreparedDocument(
                id=str(document.id),
                title=_file_name(document),
                content_type=document.mime_type or "application/octet-stream",
                mode="indexed",
                citation_id=f"document:{document.id}",
                chunks=chunks,
            ),
            _source_fingerprint(document),
        )

    async def _ensure_indexed(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> Document:
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
    ) -> Document:
        async with self._session_factory() as session:
            documents = DocumentService(session)
            document = await documents.get_document(
                document_id,
                access=access,
                include_chunks=True,
            )
            if self._index_is_current(document, access=access):
                return document
            if self._index_content_is_current(document):
                await self._vector_index.update_document_access(
                    document.id,
                    access=access,
                )
                async with self._session_factory.begin() as update_session:
                    documents = DocumentService(update_session)
                    processing = dict(document.metadata_.get("processing") or {})
                    processing.update(
                        {
                            "tenant_id": str(access.tenant_id),
                            "owner_user_id": str(access.user_id),
                        }
                    )
                    return await documents.merge_metadata(
                        document.id,
                        {"processing": processing},
                    )
            source_fingerprint = _source_fingerprint(document)
            processing = document.metadata_.get("processing")
            chunks_reusable = (
                bool(document.chunks)
                and isinstance(processing, Mapping)
                and processing.get("source_fingerprint") == source_fingerprint
                and processing.get("parser_version") == PARSER_VERSION
                and processing.get("chunker_version") == CHUNKER_VERSION
            )
            chunks = tuple(sorted(document.chunks, key=lambda item: item.chunk_index))

        try:
            if not chunks_reusable:
                canonical = await self._document_source.canonicalize(
                    document,
                    access=access,
                )
                canonical_item = canonical.item
                source_fingerprint = canonical.source_fingerprint
                canonical_chunks = canonical.chunks
                chunk_inputs = [
                    DocumentChunkInput.from_chunk(chunk) for chunk in canonical_chunks
                ]
                async with self._session_factory.begin() as session:
                    documents = DocumentService(session)
                    await documents.set_content_sha256(
                        document.id,
                        source_fingerprint,
                    )
                    chunks = tuple(
                        await documents.replace_chunks(document.id, chunk_inputs)
                    )
                    await documents.merge_metadata(
                        document.id,
                        {
                            "processing": {
                                "source_fingerprint": source_fingerprint,
                                "parser_version": PARSER_VERSION,
                                "chunker_version": CHUNKER_VERSION,
                            }
                        },
                    )
                document.content_sha256 = source_fingerprint
            else:
                canonical_chunks = tuple(
                    _canonical_chunk(document, chunk) for chunk in chunks
                )
                canonical_item = _canonical_item(
                    document,
                    access=access,
                    source_fingerprint=source_fingerprint,
                )
                async with self._session_factory.begin() as session:
                    await DocumentService(session).mark_index_pending(document.id)

            contextualizer = StructuralContextualizer()
            contextual_chunks = [
                contextualizer.contextualize(
                    chunk,
                    title=canonical_item.title,
                    source=canonical_item.source,
                    hierarchy=canonical_item.hierarchy,
                    access=canonical_item.access,
                    document_kind=canonical_item.document_kind,
                    summary=_metadata_text(canonical_item.metadata, "summary"),
                )
                for chunk in canonical_chunks
            ]
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
                source_fingerprint=source_fingerprint,
            )
            async with self._session_factory.begin() as session:
                documents = DocumentService(session)
                await documents.merge_metadata(
                    document.id,
                    {
                        "processing": {
                            "source_fingerprint": source_fingerprint,
                            "parser_version": PARSER_VERSION,
                            "chunker_version": CHUNKER_VERSION,
                            "embedding_model": self._embedder.model,
                            "tenant_id": str(access.tenant_id),
                            "owner_user_id": str(access.user_id),
                        }
                    },
                )
                return await documents.mark_indexed(document.id)
        except Exception as exc:
            async with self._session_factory.begin() as session:
                await DocumentService(session).mark_index_failed(document.id)
            if isinstance(exc, DocumentProcessingError):
                raise
            raise DocumentProcessingError("document indexing failed") from exc


def _source_fingerprint(document: Document) -> str:
    if document.content_sha256:
        return document.content_sha256
    storage = document.metadata_.get("storage")
    if isinstance(storage, Mapping):
        value = storage.get("source_fingerprint")
        if isinstance(value, str) and value:
            return value
    return f"{document.raw_storage_key or 'blob'}:{document.size_bytes or 0}"


def _advisory_lock_key(document_id: UUID) -> int:
    return int.from_bytes(document_id.bytes[:8], byteorder="big", signed=True)


def _file_name(document: Document) -> str:
    value = document.metadata_.get("file_name") or document.title or str(document.id)
    return str(value)


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _canonical_item(
    document: Document,
    *,
    access: AuthContext,
    source_fingerprint: str,
) -> DocumentItem:
    return DocumentItem(
        id=str(document.id),
        title=_file_name(document),
        source=SourceIdentity(
            connector_id="upload",
            provider=SourceProvider.FILE,
            external_id=str(document.id),
            external_version=source_fingerprint,
            etag=source_fingerprint,
            url=document.source_url,
        ),
        document_kind=_document_kind(document.mime_type),
        access=AccessPolicy.from_reader_ids([str(access.user_id)]),
        hierarchy=Hierarchy(),
        metadata={
            str(key): value if isinstance(value, str) else list(value)
            for key, value in document.metadata_.items()
            if isinstance(value, str)
            or (
                isinstance(value, (list, tuple))
                and all(isinstance(item, str) for item in value)
            )
        },
    )


def _document_kind(content_type: str | None) -> DocumentKind:
    normalized = (content_type or "").casefold()
    if normalized.startswith("image/"):
        return DocumentKind.IMAGE
    if normalized == "application/pdf":
        return DocumentKind.PDF
    if normalized in {"text/html", "application/xhtml+xml"}:
        return DocumentKind.WEB_PAGE
    return DocumentKind.DOCUMENT


def _canonical_chunk(document: Document, record: DocumentChunk) -> Chunk:
    metadata = record.metadata_
    raw_spans = metadata.get("citation_spans")
    spans: list[CitationSpan] = []
    if isinstance(raw_spans, list):
        for value in raw_spans:
            try:
                spans.append(CitationSpan.model_validate(value))
            except (TypeError, ValueError):
                continue
    if not spans:
        element_id = _metadata_text(metadata, "element_id")
        start_offset = _metadata_int(metadata, "start_offset")
        end_offset = _metadata_int(metadata, "end_offset")
        if (start_offset is None) != (end_offset is None):
            start_offset = None
            end_offset = None
        spans.append(
            CitationSpan(
                page=record.start_page_number or record.end_page_number,
                element_id=element_id,
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
    raw_section_path = metadata.get("citation_section_path")
    if not isinstance(raw_section_path, (list, tuple)):
        raw_section_path = record.heading_path or ()
    section_path = tuple(
        value
        for value in raw_section_path
        if isinstance(value, str) and value.strip()
    )
    return Chunk(
        id=_metadata_text(metadata, "chunk_id")
        or f"{document.id}:{record.chunk_index}",
        item_id=str(document.id),
        chunk_index=record.chunk_index,
        chunk_text=record.content,
        content_type=_metadata_text(metadata, "content_type") or "text",
        section_path=list(section_path),
        citation=CitationInfo(
            section=_metadata_text(metadata, "citation_section")
            or (section_path[-1] if section_path else None),
            section_path=section_path,
            anchor=_metadata_text(metadata, "citation_anchor"),
            spans=tuple(spans),
        ),
    )


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


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
