"""Canonical retrieval units derived from DocumentItem content."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .access import EffectiveAccess
from .content import BoundingBox
from .hierarchy import Hierarchy
from .source import SourceIdentity


class Chunk(BaseModel):
    """Original content fragment before contextual enrichment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    chunk_text: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    section_path: list[str] = Field(default_factory=list)
    citation: "CitationInfo"


class ChunkContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_path: list[str] = Field(default_factory=list)
    summary: str | None = None


class CitationSpan(BaseModel):
    """One immutable, element-local provenance range.

    Offsets are measured against the normalized text of ``element_id``.  A
    span deliberately does not carry item, source, or UI metadata; those
    belong to the surrounding retrieval contracts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int | None = Field(default=None, ge=1)
    element_id: str | None = Field(default=None, min_length=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    bounding_box: BoundingBox | None = None

    @model_validator(mode="after")
    def _validate_offsets(self) -> "CitationSpan":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be supplied together")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("end_offset must not precede start_offset")
        return self


class CitationInfo(BaseModel):
    """A source-independent location made from one or more provenance spans."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    section: str | None = None
    section_path: tuple[str, ...] = ()
    anchor: str | None = None
    spans: tuple[CitationSpan, ...] = ()


class ContextualChunk(BaseModel):
    """Canonical retrieval unit passed to embedding and payload projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    content_type: str = Field(min_length=1)
    chunk_text: str = Field(min_length=1)
    contextual_text: str = Field(min_length=1)
    context: ChunkContext = Field(default_factory=ChunkContext)
    title: str | None = None
    document_kind: str = Field(min_length=1)
    source: SourceIdentity
    hierarchy: Hierarchy
    access: EffectiveAccess
    citation: CitationInfo
    relevance_score: float | None = None


__all__ = ["Chunk", "ChunkContext", "CitationInfo", "CitationSpan", "ContextualChunk"]
