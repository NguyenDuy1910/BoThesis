"""Reusable single-document processing pipeline outside the agent loop."""

from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bothesis.agent.models import ConversationDocument, Evidence
from bothesis.connector.file.processing import (
    FileProcessingError,
    FileProcessor,
    ParsedDocument,
    UnsupportedFileTypeError,
)
from bothesis.connector.provider_cache import (
    ProviderCacheEntry,
    ProviderFileCache,
)
from bothesis.connector.qdrant import ChunkingConfig, split_text
from bothesis.db.models import Document, DocumentChunk
from bothesis.document_index.raw_storage import (
    DocumentStorage,
    PostgresBlobStorage,
)
from bothesis.services import (
    AuthContext,
    DocumentChunkInput,
    DocumentService,
)

log = logging.getLogger(__name__)

DEFAULT_DIRECT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_PROCESSING_MAX_BYTES = 100 * 1024 * 1024
PARSER_VERSION = "file-processor-v2"
CHUNKER_VERSION = "document-chunker-v1"

DIRECT_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})


class DocumentProcessingError(RuntimeError):
    pass


class DocumentUnavailableError(DocumentProcessingError):
    pass


class OCRUnavailableError(DocumentProcessingError):
    pass


@runtime_checkable
class Parser(Protocol):
    def parse(self, raw_bytes: bytes, *, file_name: str) -> ParsedDocument: ...


@runtime_checkable
class OCRParser(Protocol):
    async def parse(
        self,
        raw_bytes: bytes,
        *,
        file_name: str,
        content_type: str,
    ) -> ParsedDocument: ...


@runtime_checkable
class Chunker(Protocol):
    def chunk(self, document: ParsedDocument) -> list[DocumentChunkInput]: ...


@runtime_checkable
class EmbeddingService(Protocol):
    model: str

    async def embed_query(self, query: str) -> list[float]: ...

    async def embed_documents(self, documents: list[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorIndex(Protocol):
    """Derived-index operations required by the document pipeline."""

    async def replace_document(
        self,
        document: Document,
        chunks: Sequence[DocumentChunk],
        vectors: Sequence[Sequence[float]],
        *,
        access: AuthContext,
        embedding_model: str,
        source_fingerprint: str,
    ) -> None: ...

    async def search_document(
        self,
        document: Document,
        query_vector: list[float],
        *,
        access: AuthContext,
        limit: int,
    ) -> tuple[Evidence, ...]: ...

    async def update_document_access(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> None: ...

    async def soft_delete_document(self, document_id: UUID) -> None: ...


class FileParser:
    """Adapt structured file extraction to the document parser contract."""

    def __init__(self, processor: FileProcessor) -> None:
        self._processor = processor

    def parse(self, raw_bytes: bytes, *, file_name: str) -> ParsedDocument:
        return self._processor.parse_bytes(raw_bytes, file_name=file_name)


class DocumentChunker:
    def __init__(self, *, max_characters: int = 4_000, overlap_characters: int = 400):
        self._config = ChunkingConfig(
            max_characters=max_characters,
            overlap_characters=overlap_characters,
        )

    def chunk(self, document: ParsedDocument) -> list[DocumentChunkInput]:
        chunks: list[DocumentChunkInput] = []
        for section in document.sections:
            for fragment in split_text(section.content, self._config):
                chunks.append(
                    DocumentChunkInput(
                        content=fragment,
                        token_count=_approximate_tokens(fragment),
                        start_page_number=section.page_number,
                        end_page_number=section.page_number,
                        heading_path=section.heading_path,
                        metadata=section.metadata,
                    )
                )
        if not chunks:
            raise FileProcessingError("document has no indexable text")
        return chunks


@dataclass(frozen=True, slots=True)
class PreparedDocuments:
    contexts: tuple[ConversationDocument, ...]
    source_fingerprints: Mapping[UUID, str]


class DocumentPipeline:
    """Process Documents through Direct or retrieval paths.

    Chat uploads, external upload adapters, and future connectors can reuse
    this pipeline without coupling document processing to the agent loop.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        object_storage: DocumentStorage | None,
        parser: Parser,
        chunker: Chunker,
        embedder: EmbeddingService,
        vector_index: VectorIndex,
        provider_cache: ProviderFileCache,
        ocr_parser: OCRParser | None = None,
        direct_max_bytes: int = DEFAULT_DIRECT_MAX_BYTES,
        processing_max_bytes: int = DEFAULT_PROCESSING_MAX_BYTES,
        retrieval_limit: int = 6,
        embedding_batch_size: int = 32,
        download_url_seconds: int = 300,
    ) -> None:
        if (
            min(
                direct_max_bytes,
                processing_max_bytes,
                retrieval_limit,
                embedding_batch_size,
                download_url_seconds,
            )
            < 1
        ):
            raise ValueError("document processing limits must be greater than zero")
        self._session_factory = session_factory
        self._object_storage = object_storage
        self._parser = parser
        self._chunker = chunker
        self._embedder = embedder
        self._vector_index = vector_index
        self._provider_cache = provider_cache
        self._ocr_parser = ocr_parser
        self._direct_max_bytes = direct_max_bytes
        self._processing_max_bytes = processing_max_bytes
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
        contexts: list[ConversationDocument] = []
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
            await PostgresBlobStorage(session).soft_delete(document_id)
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
    ) -> tuple[ConversationDocument, str]:
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
            if document.raw_storage_key:
                if self._object_storage is None:
                    raise DocumentUnavailableError("object storage is unavailable")
                file_data = self._object_storage.presign_download(
                    document.raw_storage_key,
                    expires_seconds=self._download_url_seconds,
                ).url
            else:
                raw_bytes = await self._read_raw(document)
                file_data = f"data:{content_type};base64," + base64.b64encode(
                    raw_bytes
                ).decode("ascii")

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
            ConversationDocument(
                id=str(document.id),
                title=_file_name(document),
                content_type=content_type,
                mode="direct",
                citation_id=evidence_id,
                content_block=content_block,
                evidence=(
                    Evidence(
                        id=evidence_id,
                        document_id=str(document.id),
                        title=_file_name(document),
                        content="Original user-supplied document provided directly to the model.",
                        source="upload",
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
    ) -> tuple[ConversationDocument, str]:
        document = await self._ensure_indexed(document.id, access=access)
        query_vector = await self._embedder.embed_query(message)
        evidence = await self._vector_index.search_document(
            document,
            query_vector,
            access=access,
            limit=self._retrieval_limit,
        )
        return (
            ConversationDocument(
                id=str(document.id),
                title=_file_name(document),
                content_type=document.mime_type or "application/octet-stream",
                mode="indexed",
                citation_id=f"document:{document.id}",
                evidence=evidence,
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
                raw_bytes = await self._read_raw(document)
                digest = hashlib.sha256(raw_bytes).hexdigest()
                parsed = await self._parse(
                    raw_bytes,
                    file_name=_file_name(document),
                    content_type=document.mime_type or "application/octet-stream",
                )
                chunk_inputs = self._chunker.chunk(parsed)
                async with self._session_factory.begin() as session:
                    documents = DocumentService(session)
                    await documents.set_content_sha256(document.id, digest)
                    chunks = tuple(
                        await documents.replace_chunks(document.id, chunk_inputs)
                    )
                    await documents.merge_metadata(
                        document.id,
                        {
                            "processing": {
                                "source_fingerprint": digest,
                                "parser_version": PARSER_VERSION,
                                "chunker_version": CHUNKER_VERSION,
                            }
                        },
                    )
                document.content_sha256 = digest
                source_fingerprint = digest
            else:
                async with self._session_factory.begin() as session:
                    await DocumentService(session).mark_index_pending(document.id)

            vectors: list[list[float]] = []
            chunk_list = list(chunks)
            for start in range(0, len(chunk_list), self._embedding_batch_size):
                batch = chunk_list[start : start + self._embedding_batch_size]
                vectors.extend(
                    await self._embedder.embed_documents(
                        [chunk.content for chunk in batch]
                    )
                )
            await self._vector_index.replace_document(
                document,
                chunk_list,
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

    async def _parse(
        self,
        raw_bytes: bytes,
        *,
        file_name: str,
        content_type: str,
    ) -> ParsedDocument:
        try:
            return self._parser.parse(raw_bytes, file_name=file_name)
        except (FileProcessingError, UnsupportedFileTypeError) as exc:
            if self._ocr_parser is None:
                if (
                    content_type.startswith("image/")
                    or content_type == "application/pdf"
                ):
                    raise OCRUnavailableError(
                        "document retrieval requires OCR, but no OCR parser is configured"
                    ) from exc
                raise DocumentProcessingError(str(exc)) from exc
            return await self._ocr_parser.parse(
                raw_bytes,
                file_name=file_name,
                content_type=content_type,
            )

    async def _read_raw(
        self,
        document: Document,
    ) -> bytes:
        if (document.size_bytes or 0) > self._processing_max_bytes:
            raise DocumentProcessingError(
                "document exceeds the configured processing limit"
            )
        if document.raw_storage_key:
            if self._object_storage is None:
                raise DocumentUnavailableError("object storage is unavailable")
            raw_bytes = await self._object_storage.read(
                document.raw_storage_key,
                max_bytes=self._processing_max_bytes,
            )
        else:
            async with self._session_factory() as session:
                raw_bytes = await PostgresBlobStorage(session).read(document.id)
        if document.size_bytes is not None and len(raw_bytes) != document.size_bytes:
            raise DocumentUnavailableError(
                "stored document size no longer matches metadata"
            )
        return raw_bytes


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


def _annotation_name(annotation: Mapping[str, Any]) -> str | None:
    file_value = annotation.get("file")
    if not isinstance(file_value, Mapping):
        return None
    name = file_value.get("name")
    return name if isinstance(name, str) else None


def _approximate_tokens(value: str) -> int:
    return max(1, (len(value) + 3) // 4)


__all__ = [
    "Chunker",
    "DocumentChunker",
    "DocumentProcessingError",
    "DocumentPipeline",
    "DocumentUnavailableError",
    "EmbeddingService",
    "FileParser",
    "OCRParser",
    "OCRUnavailableError",
    "Parser",
    "PreparedDocuments",
    "VectorIndex",
]
