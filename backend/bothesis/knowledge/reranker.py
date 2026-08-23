"""Small reranking boundary over already permission-filtered chunks."""

from __future__ import annotations

from collections.abc import Sequence

from bothesis.document_index.models import ContextualChunk


class ScoreReranker:
    """Stable score ordering; provider-specific rerankers can implement this contract."""

    def rerank(self, chunks: Sequence[ContextualChunk], *, limit: int) -> list[ContextualChunk]:
        if limit < 1:
            raise ValueError("limit must be at least one")
        return sorted(
            chunks,
            key=lambda chunk: chunk.relevance_score if chunk.relevance_score is not None else float("-inf"),
            reverse=True,
        )[:limit]


__all__ = ["ScoreReranker"]
