"""Retrieval adapter for document chunks already indexed in Qdrant."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from bothesis.document_index.vector_store import VectorStore


@dataclass(frozen=True, slots=True)
class RetrievedDocument:
    """Stable, provider-independent shape returned by knowledge retrieval."""

    id: str
    document_id: str
    title: str
    content: str
    source: str | None
    uri: str | None
    metadata: Mapping[str, object]
    relevance_score: float | None = None


class KnowledgeRetriever(Protocol):
    """Read-only boundary used by the agent's knowledge-search tool."""

    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        """Return the most relevant indexed document chunks for a query."""


class QueryEmbedder(Protocol):
    """Produces one dense vector for a retrieval query."""

    async def embed_query(self, query: str) -> list[float]:
        """Embed a non-empty query for semantic search."""


class QdrantKeywordRetriever:
    """Adapts the existing Qdrant keyword search into stable document results."""

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least one")

        points, _ = await self._store.keyword_scroll(
            normalized_query,
            limit=limit,
        )
        return _normalise_points(points)


class QdrantSemanticRetriever:
    """Uses a query embedder with the existing Qdrant dense-vector search."""

    def __init__(self, store: VectorStore, embedder: QueryEmbedder) -> None:
        self._store = store
        self._embedder = embedder

    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least one")

        query_vector = await self._embedder.embed_query(normalized_query)
        points = await self._store.semantic_search(
            query_vector,
            query_filter=None,
            limit=limit,
        )
        return _normalise_points(points)


def _normalise_points(points: Sequence[object]) -> list[RetrievedDocument]:
    documents: list[RetrievedDocument] = []
    seen_ids: set[str] = set()
    for point in points:
        document = _normalise_point(point)
        if document is None or document.id in seen_ids:
            continue
        seen_ids.add(document.id)
        documents.append(document)
    return documents


def _normalise_point(point: object) -> RetrievedDocument | None:
    raw_payload = getattr(point, "payload", None)
    if not isinstance(raw_payload, Mapping):
        return None
    payload = {str(key): value for key, value in raw_payload.items()}
    content = _payload_text(payload, "content")
    if not content:
        return None

    point_id = str(getattr(point, "id", ""))
    document_id = _payload_text(payload, "document_id") or point_id
    title = (
        _payload_text(payload, "title")
        or _payload_text(payload, "section_title")
        or document_id
    )
    relevance_score = getattr(point, "score", None)
    score = float(relevance_score) if isinstance(relevance_score, (int, float)) else None
    return RetrievedDocument(
        id=point_id or document_id,
        document_id=document_id,
        title=title,
        content=content,
        source=_payload_text(payload, "source") or _payload_text(payload, "source_type"),
        uri=_payload_text(payload, "source_link"),
        metadata={key: value for key, value in payload.items() if key != "content"},
        relevance_score=score,
    )


def _payload_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


__all__ = [
    "KnowledgeRetriever",
    "QueryEmbedder",
    "QdrantKeywordRetriever",
    "QdrantSemanticRetriever",
    "RetrievedDocument",
]
