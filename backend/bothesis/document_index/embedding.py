"""Embedding and tokenizer boundaries for contextual chunks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .models import ContextualChunk


@runtime_checkable
class EmbeddingService(Protocol):
    model: str

    async def embed_query(self, query: str) -> list[float]: ...

    async def embed_documents(self, documents: list[str]) -> list[list[float]]: ...


@runtime_checkable
class EmbeddingTokenizer(Protocol):
    def count(self, text: str) -> int: ...


def embedding_texts(chunks: Sequence[ContextualChunk]) -> list[str]:
    """Return enriched text only; source ``chunk_text`` remains evidence."""

    return [chunk.contextual_text for chunk in chunks]


__all__ = ["EmbeddingService", "EmbeddingTokenizer", "embedding_texts"]
