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
    reader_ids: tuple[str, ...]
    is_admin: bool
    connector_ids: tuple[int, ...] | None


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    item_id: str
    chunk_id: str
    title: str
    content: str
    source: SourceIdentity | None = None
    citation: CitationInfo = field(default_factory=CitationInfo)
    relevance_score: float | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    query: str
    limit: int = 10
    filters: Mapping[str, object] = field(default_factory=dict)


__all__ = ["Evidence", "KnowledgeQuery", "RetrievalContext"]
