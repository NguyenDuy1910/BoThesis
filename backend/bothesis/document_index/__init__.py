"""Contextualization, embedding, payload projection, and Item indexing."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bothesis.connector.protocol import (
    Chunk,
    CitationInfo,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
)

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


class ChunkContext(BaseModel):
    """Structural and optional semantic context attached to an Item chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    section_path: list[str] = Field(default_factory=list)
    summary: str | None = None


class ContextualChunk(BaseModel):
    """Storage-neutral indexed Item chunk returned to knowledge retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    content_type: str = Field(min_length=1)
    chunk_text: str = Field(min_length=1)
    contextual_text: str = Field(min_length=1)
    context: ChunkContext = Field(default_factory=ChunkContext)
    title: str | None = None
    document_type: str = Field(min_length=1)
    collection_item_id: str | None = None
    source: SourceIdentity
    hierarchy: Hierarchy
    access: EffectiveAccess
    citation: CitationInfo
    relevance_score: float | None = None
    rerank_score: float | None = None


from .contextualization import (
    ContextualChunkBuilder,
    build_contextual_chunks,
)
from .semantic_contextualizer import SemanticContextualizer

@runtime_checkable
class EmbeddingService(Protocol):
    """Provider-neutral embedding operations used by document indexing."""

    embedding_model: str

    async def embed_documents(self, documents: list[str]) -> list[list[float]]: ...

    async def embed_query(self, query: str) -> list[float]: ...


class ItemContentIndex(Protocol):
    """Read-only, storage-neutral search boundary consumed by knowledge."""

    async def search_item_content(
        self,
        query: str,
        *,
        limit: int,
        tenant_id: str,
        collection_item_ids: tuple[str, ...],
    ) -> list[ContextualChunk]:
        """Return indexed chunks after applying the supplied access scope."""


from .index import ItemIndex

__all__ = [
    "BM25_MODEL",
    "BM25_OPTIONS",
    "DEFAULT_HYBRID_CANDIDATE_LIMIT",
    "DENSE_VECTOR_NAME",
    "INDEX_SCHEMA_VERSION",
    "SPARSE_VECTOR_NAME",
    "ChunkContext",
    "ChunkContextGenerator",
    "ContextualChunk",
    "ContextualChunkBuilder",
    "EmbeddingService",
    "IndexingContext",
    "ItemContentIndex",
    "ItemIndex",
    "SemanticContextualizer",
    "build_contextual_chunks",
]
