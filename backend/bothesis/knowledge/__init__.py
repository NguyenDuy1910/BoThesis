"""Retrieval semantics and evidence construction."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from typing import Protocol, runtime_checkable

from bothesis.document_index.models import ContextualChunk

from .evidence import CitationResolver, EvidenceBuilder
from .models import Evidence, EvidenceContext, KnowledgeQuery, RetrievalContext
from .context_builder import EvidenceContextBuilder
from .semantic_reranker import SemanticReranker


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
        query: str = "",
    ) -> list[ContextualChunk] | Awaitable[list[ContextualChunk]]:
        """Return at most ``limit`` chunks in relevance order."""


class ContextBuilder(Protocol):
    """Build bounded model context from ranked canonical evidence."""

    def build(self, evidence: Sequence[Evidence]) -> EvidenceContext:
        """Return context plus only the evidence actually represented."""


__all__ = [
    "CitationResolver",
    "Evidence",
    "EvidenceContext",
    "EvidenceContextBuilder",
    "EvidenceBuilder",
    "ContextBuilder",
    "KnowledgeQuery",
    "KnowledgeRetriever",
    "Reranker",
    "RetrievalContext",
    "SemanticReranker",
]
