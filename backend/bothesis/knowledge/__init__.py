"""Retrieval semantics and evidence construction."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from bothesis.document_index.models import ContextualChunk

from .evidence import CitationResolver, EvidenceBuilder
from .models import Evidence, KnowledgeQuery, RetrievalContext


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """Tenant-scoped evidence retrieval boundary consumed by agents."""

    async def search(
        self,
        query: str,
        *,
        limit: int,
        ctx: RetrievalContext,
    ) -> list[Evidence]:
        """Return only evidence visible to the supplied tenant context."""


class Reranker(Protocol):
    """Order chunks that have already passed permission filtering."""

    def rerank(
        self,
        chunks: Sequence[ContextualChunk],
        *,
        limit: int,
    ) -> list[ContextualChunk]:
        """Return at most ``limit`` chunks in relevance order."""


__all__ = [
    "CitationResolver",
    "Evidence",
    "EvidenceBuilder",
    "KnowledgeQuery",
    "KnowledgeRetriever",
    "Reranker",
    "RetrievalContext",
]
