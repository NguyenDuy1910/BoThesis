"""Provider-independent representations used by the indexing boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bothesis.connector.protocol import (
    BoundingBox,
    CitationInfo,
    CitationSpan,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)


class ChunkContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_path: list[str] = Field(default_factory=list)
    summary: str | None = None


class ContextualChunk(BaseModel):
    """Enriched connector chunk passed to embedding and vector projection."""

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


class IndexQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


@dataclass(frozen=True, slots=True)
class PreparedDocument:
    """Document-index output ready for an agent-side context adapter."""

    id: str
    title: str
    content_type: str
    mode: Literal["direct", "indexed"]
    citation_id: str
    content_block: Mapping[str, Any] | None = None
    extracted_text: str | None = None
    chunks: tuple[ContextualChunk, ...] = ()
    provider_annotations: tuple[Mapping[str, Any], ...] = ()


__all__ = [
    "BoundingBox",
    "ChunkContext",
    "CitationInfo",
    "CitationSpan",
    "ContextualChunk",
    "EffectiveAccess",
    "Hierarchy",
    "IndexQuery",
    "PreparedDocument",
    "SourceIdentity",
    "SourceProvider",
]
