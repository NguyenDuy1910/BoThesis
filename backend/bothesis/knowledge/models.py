"""Retrieval and evidence contracts owned by the knowledge domain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from bothesis.document_index.models import CitationInfo, SourceIdentity


class RetrievalContext(Protocol):
    tenant_id: str
    user_id: str
    roles: list[str]
    collection_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    item_id: str
    chunk_id: str
    title: str
    content: str
    collection_item_id: str | None = None
    source: SourceIdentity | None = None
    citation: CitationInfo = field(default_factory=CitationInfo)
    section_path: tuple[str, ...] = ()
    contextual_text: str | None = None
    relevance_score: float | None = None
    rerank_score: float | None = None


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    """Bounded model context and the exact evidence represented in it."""

    text: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    query: str
    limit: int = 10
    filters: Mapping[str, object] = field(default_factory=dict)


__all__ = ["Evidence", "EvidenceContext", "KnowledgeQuery", "RetrievalContext"]
