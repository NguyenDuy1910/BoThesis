"""Permission-scoped retrieval orchestration over a document index."""

from __future__ import annotations

from bothesis.document_index import DocumentIndex
from bothesis.knowledge import (
    Evidence,
    EvidenceBuilder,
    KnowledgeRetriever,
    Reranker,
    RetrievalContext,
)
from bothesis.knowledge.filters import filter_visible_chunks
from bothesis.knowledge.reranker import ScoreReranker


class DocumentIndexRetriever:
    """Build tenant-scoped evidence from filtered and reranked index chunks."""

    def __init__(
        self,
        index: DocumentIndex,
        *,
        reranker: Reranker | None = None,
        evidence_builder: EvidenceBuilder | None = None,
    ) -> None:
        self._index = index
        self._reranker = reranker or ScoreReranker()
        self._evidence_builder = evidence_builder or EvidenceBuilder()

    async def search(
        self,
        query: str,
        *,
        limit: int,
        ctx: RetrievalContext,
    ) -> list[Evidence]:
        normalized_query = _validate_search(query, limit=limit)
        tenant_id = _validate_tenant_id(ctx.tenant_id)
        if not ctx.collection_item_ids:
            return []
        chunks = await self._index.search(
            normalized_query,
            limit=limit,
            tenant_id=tenant_id,
            collection_item_ids=ctx.collection_item_ids,
        )
        visible_chunks = filter_visible_chunks(
            chunks,
            context=ctx,
        )
        reranked_chunks = self._reranker.rerank(visible_chunks, limit=limit)
        return [self._evidence_builder.build(chunk) for chunk in reranked_chunks]


def _validate_search(query: str, *, limit: int) -> str:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if limit < 1:
        raise ValueError("limit must be at least one")
    return normalized_query


def _validate_tenant_id(tenant_id: str) -> str:
    normalized_tenant_id = tenant_id.strip() if isinstance(tenant_id, str) else ""
    if not normalized_tenant_id:
        raise ValueError("tenant_id must not be empty")
    return normalized_tenant_id


__all__ = [
    "DocumentIndexRetriever",
    "KnowledgeRetriever",
]
