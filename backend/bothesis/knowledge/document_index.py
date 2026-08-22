"""Permission-scoped reconstruction of contextual chunks from Qdrant."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from bothesis.agent.models import AgentContext
from bothesis.document_index.vector_store import VectorStore
from bothesis.knowledge.protocol import (
    BoundingBox,
    CitationInfo,
    CitationSpan,
    ChunkContext,
    ContextualChunk,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)


class KnowledgeRetriever(Protocol):
    """Read-only boundary returning canonical contextual chunks."""

    async def search(self, query: str, *, limit: int) -> list[ContextualChunk]:
        """Return the most relevant indexed chunks for a query."""


@runtime_checkable
class ScopedKnowledgeRetriever(Protocol):
    """Retrieval boundary that enforces the authenticated agent scope."""

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[ContextualChunk]:
        """Return only chunks visible to the supplied agent context."""


class QueryEmbedder(Protocol):
    """Produces one dense vector for a retrieval query."""

    async def embed_query(self, query: str) -> list[float]:
        """Embed a non-empty query for semantic search."""


class QdrantKeywordRetriever:
    """Adapt Qdrant keyword search into canonical contextual chunks."""

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    async def search(self, query: str, *, limit: int) -> list[ContextualChunk]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least one")

        points, _ = await self._store.keyword_scroll(normalized_query, limit=limit)
        return _normalise_points(points)


class QdrantSemanticRetriever:
    """Use a query embedder with permission-scoped Qdrant vector search."""

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

    async def search(self, query: str, *, limit: int) -> list[ContextualChunk]:
        """Unscoped search for public/non-sensitive deployments only."""

        return await self._search(query, limit=limit, query_filter=None)

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[ContextualChunk]:
        if ctx.connector_ids == ():
            return []
        if (
            self._allow_unscoped_admin_retrieval
            and ctx.is_admin
            and ctx.connector_ids is None
        ):
            query_filter = self._store.build_lifecycle_filter()
        else:
            query_filter = self._store.build_retrieval_filter(
                None,
                access_context=_retrieval_access(ctx),
                payload_filters=ctx,
            )
        return await self._search(query, limit=limit, query_filter=query_filter)

    async def _search(
        self,
        query: str,
        *,
        limit: int,
        query_filter: object | None,
    ) -> list[ContextualChunk]:
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


class _RetrievalAccess:
    def __init__(
        self,
        *,
        tenant_id: str,
        reader_ids: tuple[str, ...],
        space_keys: tuple[str, ...] = (),
        is_admin: bool = False,
    ) -> None:
        self.tenant_id = tenant_id
        self.reader_ids = reader_ids
        self.space_keys = space_keys
        self.is_admin = is_admin


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


def _normalise_points(points: Sequence[object]) -> list[ContextualChunk]:
    chunks: list[ContextualChunk] = []
    seen_ids: set[str] = set()
    for point in points:
        chunk = _normalise_point(point)
        if chunk is None or chunk.id in seen_ids:
            continue
        seen_ids.add(chunk.id)
        chunks.append(chunk)
    return chunks


def _normalise_point(point: object) -> ContextualChunk | None:
    raw_payload = getattr(point, "payload", None)
    if not isinstance(raw_payload, Mapping):
        return None
    payload = {str(key): value for key, value in raw_payload.items()}
    item_id = _payload_text(payload, "item_id")
    chunk_id = _payload_text(payload, "chunk_id")
    chunk_text = _payload_text(payload, "chunk_text")
    contextual_text = _payload_text(payload, "contextual_text")
    provider_value = _payload_text(payload, "provider")
    external_id = _payload_text(payload, "external_id")
    if not all((item_id, chunk_id, chunk_text, contextual_text, provider_value, external_id)):
        return None
    try:
        provider = SourceProvider(provider_value)
    except ValueError:
        return None

    point_score = getattr(point, "score", None)
    score = float(point_score) if isinstance(point_score, (int, float)) else None
    section_path = _payload_strings(payload, "context_section_path")
    citation_section_path = _payload_strings(payload, "citation_section_path")
    return ContextualChunk(
        id=chunk_id,
        item_id=item_id,
        chunk_index=_payload_int(payload, "chunk_index", default=0),
        content_type=_payload_text(payload, "content_type") or "text",
        chunk_text=chunk_text,
        contextual_text=contextual_text,
        context=ChunkContext(
            section_path=section_path,
            summary=_payload_text(payload, "context_summary"),
        ),
        title=_payload_text(payload, "title"),
        document_kind=_payload_text(payload, "document_kind") or "document",
        source=SourceIdentity(
            connector_id=str(payload.get("connector_id") or "unknown"),
            provider=provider,
            external_id=external_id,
            url=_payload_text(payload, "source_url"),
        ),
        hierarchy=Hierarchy(
            parent_id=_payload_text(payload, "parent_id"),
            root_id=_payload_text(payload, "root_id"),
            ancestor_ids=_payload_strings(payload, "ancestor_ids"),
        ),
        access=EffectiveAccess(reader_ids=_payload_strings(payload, "reader_ids")),
        citation=CitationInfo(
            section=_payload_text(payload, "citation_section"),
            section_path=tuple(citation_section_path),
            anchor=_payload_text(payload, "citation_anchor"),
            spans=tuple(_payload_spans(payload.get("citation_spans"))),
        ),
        relevance_score=score,
    )


def _payload_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _payload_strings(payload: Mapping[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _payload_int(
    payload: Mapping[str, object],
    key: str,
    *,
    default: int | None = None,
) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return default


def _payload_bbox(value: object) -> BoundingBox | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return BoundingBox.model_validate(value)
    except ValueError:
        return None


def _payload_spans(value: object) -> list[CitationSpan]:
    if not isinstance(value, (list, tuple)):
        return []
    spans: list[CitationSpan] = []
    for raw_span in value:
        if not isinstance(raw_span, Mapping):
            continue
        try:
            spans.append(
                CitationSpan(
                    page=_payload_int(raw_span, "page"),
                    element_id=_payload_text(raw_span, "element_id"),
                    start_offset=_payload_int(raw_span, "start_offset"),
                    end_offset=_payload_int(raw_span, "end_offset"),
                    bounding_box=_payload_bbox(raw_span.get("bounding_box")),
                )
            )
        except ValueError:
            continue
    return spans


__all__ = [
    "KnowledgeRetriever",
    "QdrantKeywordRetriever",
    "QdrantSemanticRetriever",
    "QueryEmbedder",
    "ScopedKnowledgeRetriever",
]
