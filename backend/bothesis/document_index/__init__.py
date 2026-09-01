"""Contextualization, embedding, payload projection, and vector indexing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bothesis.connector.protocol import Chunk

INDEX_SCHEMA_VERSION = 11
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


class IndexingContext(BaseModel):
    """Index-scoped values that are not part of a connector chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1)
    collection_item_id: str = Field(min_length=1)
    parent_item_id: str | None = None
    document_type: str = Field(min_length=1)
    connector_key: str = Field(min_length=1)

    @field_validator(
        "tenant_id",
        "collection_item_id",
        "document_type",
        "connector_key",
    )
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("indexing context values must not be blank")
        return value

    @field_validator("parent_item_id")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


@runtime_checkable
class ChunkContextGenerator(Protocol):
    """Optional semantic context generation used before chunk embedding."""

    @property
    def model_name(self) -> str | None: ...

    async def describe(
        self,
        chunk: Chunk,
        *,
        document_context: str,
        title: str | None = None,
        section_path: Sequence[str] = (),
    ) -> str | None: ...


from .contextualization import (  # noqa: E402
    ContextualChunkBuilder,
    StructuralContextualizer,
    build_contextual_chunks,
)
from .semantic_contextualizer import SemanticContextualizer  # noqa: E402
from .models import ChunkContext, ContextualChunk, IndexQuery, PreparedDocument
from .payload import (
    IndexedChunk,
    build_index_records,
    contextual_chunk_from_point,
)


class IndexedChunkRecord(BaseModel):
    """A deterministic point identifier paired with its indexed chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point_id: str = Field(min_length=1)
    payload: IndexedChunk

    @classmethod
    def from_contextual_chunk(
        cls,
        chunk: ContextualChunk,
        context: IndexingContext,
    ) -> "IndexedChunkRecord":
        return cls(
            point_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{context.tenant_id}:{chunk.item_id}:{chunk.chunk_index}",
                )
            ),
            payload=IndexedChunk.from_contextual_chunk(chunk, context),
        )


if TYPE_CHECKING:
    from bothesis.db.models import Item


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
        context: IndexingContext,
    ) -> None: ...

    async def soft_delete_document(
        self,
        document_id: UUID,
        *,
        tenant_id: str | None = None,
    ) -> None: ...

    async def aclose(self) -> None: ...


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
    "BM25_MODEL",
    "BM25_OPTIONS",
    "CHUNKER_VERSION",
    "ChunkContext",
    "ChunkContextGenerator",
    "ContextualChunk",
    "ContextualChunkBuilder",
    "DEFAULT_DIRECT_MAX_BYTES",
    "DEFAULT_HYBRID_CANDIDATE_LIMIT",
    "DENSE_VECTOR_NAME",
    "DIRECT_IMAGE_TYPES",
    "DocumentIndex",
    "DocumentProcessingError",
    "DocumentUnavailableError",
    "EmbeddingService",
    "INDEX_SCHEMA_VERSION",
    "IndexedChunk",
    "IndexedChunkRecord",
    "IndexingContext",
    "IndexQuery",
    "PARSER_VERSION",
    "PreparedDocument",
    "PreparedDocuments",
    "SPARSE_VECTOR_NAME",
    "SemanticContextualizer",
    "StructuralContextualizer",
    "VectorIndex",
    "build_contextual_chunks",
    "build_index_records",
    "contextual_chunk_from_point",
]
