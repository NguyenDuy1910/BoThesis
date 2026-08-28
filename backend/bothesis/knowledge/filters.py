"""Defensive Collection scope filtering for retrieval results."""

from __future__ import annotations

from collections.abc import Sequence

from bothesis.document_index.models import ContextualChunk
from bothesis.knowledge.models import RetrievalContext


def filter_visible_chunks(
    chunks: Sequence[ContextualChunk], *, context: RetrievalContext
) -> list[ContextualChunk]:
    """Keep only chunks projected into an authorized Collection."""

    allowed = set(context.collection_item_ids)
    return [chunk for chunk in chunks if chunk.collection_item_id in allowed]


__all__ = ["filter_visible_chunks"]
