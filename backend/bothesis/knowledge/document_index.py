"""Retrieval adapter for document chunks already indexed in Qdrant."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from bothesis.agent.models import AgentContext
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


@runtime_checkable
class ScopedKnowledgeRetriever(Protocol):
    """Retrieval boundary that enforces the authenticated agent scope."""

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[RetrievedDocument]:
        """Return only documents visible to the supplied agent context."""


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

    def __init__(
        self,
        store: VectorStore,
        embedder: QueryEmbedder,
        *,
        allow_unscoped_admin_retrieval: bool = False,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._allow_unscoped_admin_retrieval = allow_unscoped_admin_retrieval

    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        """Compatibility search; callers handling private data use search_scoped."""

        return await self._search(query, limit=limit, query_filter=None)

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[RetrievedDocument]:
        if self._allow_unscoped_admin_retrieval and ctx.is_admin:
            query_filter = self._store.build_lifecycle_filter()
        else:
            access = _retrieval_access(ctx)
            query_filter = self._store.build_retrieval_filter(
                None,
                access_context=access,
            )
        return await self._search(query, limit=limit, query_filter=query_filter)

    async def _search(
        self,
        query: str,
        *,
        limit: int,
        query_filter: object | None,
    ) -> list[RetrievedDocument]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least one")

        query_vector = await self._embedder.embed_query(normalized_query)
        points = await self._store.semantic_search(
            query_vector,
            query_filter=query_filter,
            limit=limit,
        )
        return _normalise_points(points)


@dataclass(frozen=True, slots=True)
class _RetrievalAccess:
    tenant_id: str
    reader_ids: tuple[str, ...]
    space_keys: tuple[str, ...] = ()
    is_admin: bool = False


def _retrieval_access(ctx: AgentContext) -> _RetrievalAccess:
    user = ctx.user_id.strip().lower()
    reader_ids = {"public", user}
    if "@" in user:
        reader_ids.add(f"email:{user}")
    reader_ids.update(
        reader_id.strip().lower()
        for reader_id in ctx.reader_ids
        if reader_id.strip()
    )
    reader_ids.update(
        f"external_group:{role.strip().lower()}"
        for role in ctx.roles
        if role.strip()
    )
    return _RetrievalAccess(
        tenant_id=ctx.tenant_id,
        reader_ids=tuple(sorted(reader_ids)),
        is_admin=ctx.is_admin,
    )


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
    "ScopedKnowledgeRetriever",
]
