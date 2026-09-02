"""Permission-scoped retrieval orchestration over a document index."""

from __future__ import annotations

import inspect
import logging

from bothesis.document_index import DocumentIndex
from bothesis.document_index.models import ContextualChunk
from bothesis.knowledge import (
    Evidence,
    EvidenceBuilder,
    KnowledgeRetriever,
    Reranker,
    RetrievalContext,
)
from bothesis.knowledge.filters import filter_visible_chunks
from bothesis.knowledge.reranker import ScoreReranker

log = logging.getLogger(__name__)


class DocumentIndexRetriever:
    """Build tenant-scoped evidence from filtered and reranked index chunks."""

    def __init__(
        self,
        index: DocumentIndex,
        *,
        reranker: Reranker | None = None,
        evidence_builder: EvidenceBuilder | None = None,
        candidate_count: int = 20,
        reranking_enabled: bool = True,
    ) -> None:
        if candidate_count < 1:
            raise ValueError("candidate_count must be at least one")
        self._index = index
        self._reranker = reranker or ScoreReranker()
        self._evidence_builder = evidence_builder or EvidenceBuilder()
        self._candidate_count = candidate_count
        self._reranking_enabled = reranking_enabled

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
            limit=max(limit, self._candidate_count),
            tenant_id=tenant_id,
            collection_item_ids=ctx.collection_item_ids,
        )
        visible_chunks = filter_visible_chunks(
            chunks,
            context=ctx,
        )
        reranked_chunks = await self._rerank(
            visible_chunks,
            query=normalized_query,
            limit=limit,
        )
        return [self._evidence_builder.build(chunk) for chunk in reranked_chunks]

    async def _rerank(
        self,
        chunks: list[ContextualChunk],
        *,
        query: str,
        limit: int,
    ) -> list[ContextualChunk]:
        if not self._reranking_enabled:
            return chunks[:limit]
        try:
            parameters = inspect.signature(self._reranker.rerank).parameters
            if "query" in parameters:
                result = self._reranker.rerank(
                    chunks,
                    query=query,
                    limit=limit,
                )
            else:
                # Preserve compatibility with existing score-only rerankers.
                result = self._reranker.rerank(chunks, limit=limit)
            if inspect.isawaitable(result):
                result = await result
            ranked = list(result)
            if any(not isinstance(chunk, ContextualChunk) for chunk in ranked):
                raise ValueError("reranker returned invalid candidates")
            allowed = {chunk.id for chunk in chunks}
            ranked_ids = [chunk.id for chunk in ranked]
            if (
                not set(ranked_ids).issubset(allowed)
                or len(ranked_ids) != len(set(ranked_ids))
            ):
                raise ValueError("reranker returned invalid candidates")
            return ranked[:limit]
        except Exception as exc:
            log.warning(
                "retrieval reranking failed; preserving candidate order: %s",
                type(exc).__name__,
            )
            return chunks[:limit]


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
