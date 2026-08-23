"""Contextualization, embedding, payload projection, and vector indexing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

from .contextualization import SemanticContextualizer, StructuralContextualizer
from .embedding import EmbeddingService, EmbeddingTokenizer, embedding_texts
from .models import ChunkContext, ContextualChunk, IndexQuery, PreparedDocument
from .payload import (
    IndexPayload,
    QdrantChunkPayload,
    QdrantChunkRecord,
    QdrantPayloadContext,
    build_contextual_chunks,
    build_qdrant_records,
)

if TYPE_CHECKING:
    from bothesis.db.models import Document
    from bothesis.services import AuthContext


DEFAULT_DIRECT_MAX_BYTES = 20 * 1024 * 1024
PARSER_VERSION = "docling-2.121"
CHUNKER_VERSION = "docling-hybrid-line-v1"
DIRECT_IMAGE_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)


class DocumentProcessingError(RuntimeError):
    """Raised when a chat document cannot be prepared for indexing."""


class DocumentUnavailableError(DocumentProcessingError):
    """Raised when an authorized document's raw content is unavailable."""


@runtime_checkable
class VectorIndex(Protocol):
    """Derived-index operations required by the document pipeline."""

    async def replace_document(
        self,
        document: Document,
        chunks: Sequence[ContextualChunk],
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
    ) -> tuple[ContextualChunk, ...]: ...

    async def update_document_access(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> None: ...

    async def soft_delete_document(self, document_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class PreparedDocuments:
    """Model-ready chat document contexts and their source fingerprints."""

    contexts: tuple[PreparedDocument, ...]
    source_fingerprints: Mapping[UUID, str]


class DocumentIndex(Protocol):
    """Read-only, storage-neutral search boundary consumed by knowledge."""

    async def search(
        self,
        query: str,
        *,
        limit: int,
        tenant_id: str,
        reader_ids: tuple[str, ...],
        connector_ids: tuple[int, ...] | None,
        is_admin: bool,
    ) -> list[ContextualChunk]:
        """Return indexed chunks after applying the supplied access scope."""


__all__ = [
    "CHUNKER_VERSION", "ChunkContext", "ContextualChunk",
    "DEFAULT_DIRECT_MAX_BYTES", "DIRECT_IMAGE_TYPES", "DocumentIndex",
    "DocumentProcessingError", "DocumentUnavailableError", "EmbeddingService",
    "EmbeddingTokenizer", "IndexPayload", "IndexQuery",
    "PARSER_VERSION", "PreparedDocument", "PreparedDocuments",
    "QdrantChunkPayload", "QdrantChunkRecord",
    "QdrantPayloadContext",
    "SemanticContextualizer", "StructuralContextualizer", "build_contextual_chunks",
    "build_qdrant_records",
    "VectorIndex", "embedding_texts",
]
