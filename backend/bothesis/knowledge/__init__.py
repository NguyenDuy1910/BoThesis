"""Permission-scoped knowledge retrieval and grounded evidence contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from bothesis.connector.protocol import CitationInfo, SourceIdentity
from bothesis.document_index import ContextualChunk


class RetrievalContext(Protocol):
    """Minimum authenticated scope required by knowledge retrieval."""

    tenant_id: str
    user_id: str
    roles: list[str]
    collection_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Evidence:
    """Canonical source evidence safe to pass to the agent."""

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


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """Tenant-scoped evidence retrieval boundary consumed by agents."""

    async def search(
        self,
        query: str,
        *,
        limit: int,
        ctx: RetrievalContext,
    ) -> list[Evidence]: ...


class Reranker(Protocol):
    """Optional second-stage ordering over permission-filtered chunks."""

    def rerank(
        self,
        chunks: Sequence[ContextualChunk],
        *,
        limit: int,
        query: str = "",
    ) -> list[ContextualChunk] | Awaitable[list[ContextualChunk]]: ...


class ContextBuilder(Protocol):
    """Build bounded model context from ranked canonical evidence."""

    def build(self, evidence: Sequence[Evidence]) -> EvidenceContext: ...


from .context_builder import EvidenceContextBuilder
from .evidence import CitationResolver
from .retriever import ItemKnowledgeRetriever, source_reference
from .semantic_reranker import SemanticReranker

__all__ = [
    "CitationResolver",
    "ContextBuilder",
    "Evidence",
    "EvidenceContext",
    "EvidenceContextBuilder",
    "ItemKnowledgeRetriever",
    "KnowledgeRetriever",
    "Reranker",
    "RetrievalContext",
    "SemanticReranker",
    "source_reference",
]
