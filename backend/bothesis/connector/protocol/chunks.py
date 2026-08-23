"""Canonical normalized evidence chunks produced by connectors."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .citation import CitationInfo


class Chunk(BaseModel):
    """Original source evidence and its stable connector-owned provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    chunk_text: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    section_path: list[str] = Field(default_factory=list)
    citation: CitationInfo


__all__ = ["Chunk"]
