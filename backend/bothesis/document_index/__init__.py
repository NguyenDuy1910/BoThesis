"""Contextualization, embedding, payload projection, and vector indexing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

INDEX_SCHEMA_VERSION = 7
DENSE_VECTOR_NAME = "content"
SPARSE_VECTOR_NAME = "content_bm25"
BM25_MODEL = "qdrant/bm25"
BM25_OPTIONS: dict[str, Any] = {
    "tokenizer": "multilingual",
    "stemmer": {"type": "none"},
    "stopwords": {"custom": []},
    "lowercase": True,
    "ascii_folding": False,
}
DEFAULT_HYBRID_CANDIDATE_LIMIT = 20


from .contextualization import StructuralContextualizer  # noqa: E402
from .semantic_contextualizer import SemanticContextualizer  # noqa: E402
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
    from bothesis.db.models import Item
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
class EmbeddingService(Protocol):
    """Provider-neutral embedding operations used by document indexing."""

    embedding_model: str

    async def embed_query(self, query: str) -> list[float]: ...

    async def embed_documents(self, documents: list[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorIndex(Protocol):
    """Derived-index operations required by the document pipeline."""

    async def replace_document(
        self,
        document: Item,
        chunks: Sequence[ContextualChunk],
        vectors: Sequence[Sequence[float]],
        *,
        access: AuthContext,
        embedding_model: str,
    ) -> None: ...

    async def search_document(
        self,
        document: Item,
        query: str,
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
    """Model-ready chat document contexts."""

    contexts: tuple[PreparedDocument, ...]


class DocumentIndex(Protocol):
    """Read-only, storage-neutral search boundary consumed by knowledge."""

    async def search(
        self,
        query: str,
        *,
        limit: int,
        tenant_id: str,
        collection_item_ids: tuple[str, ...],
    ) -> list[ContextualChunk]:
        """Return indexed chunks after applying the supplied access scope."""


__all__ = [
    "BM25_MODEL", "BM25_OPTIONS", "CHUNKER_VERSION", "ChunkContext",
    "ContextualChunk", "DEFAULT_HYBRID_CANDIDATE_LIMIT", "DENSE_VECTOR_NAME",
    "DEFAULT_DIRECT_MAX_BYTES", "DIRECT_IMAGE_TYPES", "DocumentIndex",
    "DocumentProcessingError", "DocumentUnavailableError", "EmbeddingService",
    "IndexPayload", "IndexQuery",
    "PARSER_VERSION", "PreparedDocument", "PreparedDocuments",
    "QdrantChunkPayload", "QdrantChunkRecord",
    "QdrantPayloadContext", "INDEX_SCHEMA_VERSION", "SPARSE_VECTOR_NAME",
    "SemanticContextualizer", "StructuralContextualizer",
    "build_contextual_chunks",
    "build_qdrant_records",
    "VectorIndex",
]
