"""Read-only vector search adapter for contextual document chunks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from bothesis.document_index import (
    DEFAULT_HYBRID_CANDIDATE_LIMIT,
    contextual_chunk_from_point,
)
from bothesis.document_index.models import ContextualChunk


class _VectorStore(Protocol):
    def build_retrieval_filter(
        self,
        search_params: object | None,
        *,
        access_context: object,
        payload_filters: object,
    ) -> object:
        """Build a tenant, ACL, lifecycle, and payload filter."""

    async def semantic_search(
        self,
        query_vector: list[float],
        *,
        query_text: str,
        query_filter: object,
        limit: int,
        candidate_limit: int,
    ) -> list[object]:
        """Search the configured vector collection."""


class _QueryEmbedder(Protocol):
    async def embed_query(self, query: str) -> list[float]:
        """Embed a non-empty retrieval query."""


class VectorSearchIndex:
    """Embed queries, search the vector store, and rebuild indexed chunks."""

    def __init__(
        self,
        store: _VectorStore,
        embedder: _QueryEmbedder,
        *,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least one")
        self._store = store
        self._embedder = embedder
        self._candidate_limit = candidate_limit

    async def search(
        self,
        query: str,
        *,
        limit: int,
        tenant_id: str,
        collection_item_ids: tuple[str, ...],
    ) -> list[ContextualChunk]:
        """Return chunks after applying lifecycle and authenticated scope filters."""

        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least one")
        normalized_tenant_id = (
            tenant_id.strip() if isinstance(tenant_id, str) else ""
        )
        if not normalized_tenant_id:
            raise ValueError("tenant_id must not be empty")
        if not collection_item_ids:
            return []

        query_filter = self._store.build_retrieval_filter(
            None,
            access_context=_RetrievalAccess(
                tenant_id=normalized_tenant_id,
                collection_item_ids=collection_item_ids,
            ),
            payload_filters=_PayloadFilters(),
        )

        query_vector = await self._embedder.embed_query(normalized_query)
        points = await self._store.semantic_search(
            query_vector,
            query_text=normalized_query,
            query_filter=query_filter,
            limit=limit,
            candidate_limit=max(limit, self._candidate_limit),
        )
        return _normalise_points(points)


class _RetrievalAccess:
    def __init__(
        self,
        *,
        tenant_id: str,
        collection_item_ids: tuple[str, ...],
    ) -> None:
        self.tenant_id = tenant_id
        self.collection_item_ids = collection_item_ids


class _PayloadFilters:
    pass


def _normalise_points(points: Sequence[object]) -> list[ContextualChunk]:
    chunks: list[ContextualChunk] = []
    seen_ids: set[str] = set()
    for point in points:
        chunk = contextual_chunk_from_point(point)
        if chunk is None or chunk.id in seen_ids:
            continue
        seen_ids.add(chunk.id)
        chunks.append(chunk)
    return chunks


__all__ = ["VectorSearchIndex"]
