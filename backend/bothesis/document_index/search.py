"""Read-only vector search adapter for contextual document chunks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from bothesis.connector.protocol import (
    CitationInfo,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index import DEFAULT_HYBRID_CANDIDATE_LIMIT
from bothesis.document_index.models import ChunkContext, ContextualChunk


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
    chunk_text = _payload_content(payload, "chunk_text")
    contextual_text = _payload_content(payload, "contextual_text")
    provider_value = _payload_text(payload, "connector_key")
    external_id = _payload_text(payload, "external_id")
    if not all(
        (
            item_id,
            chunk_id,
            chunk_text,
            contextual_text,
            provider_value,
            external_id,
        )
    ):
        return None
    try:
        provider = SourceProvider(provider_value)
    except ValueError:
        return None

    point_score = getattr(point, "score", None)
    score = float(point_score) if isinstance(point_score, (int, float)) else None
    section_path = _payload_strings(payload, "section_path")
    return ContextualChunk(
        id=chunk_id,
        item_id=item_id,
        chunk_index=_payload_int(payload, "chunk_index", default=0),
        content_type=_payload_text(payload, "content_type") or "text",
        chunk_text=chunk_text,
        contextual_text=contextual_text,
        context=ChunkContext(
            section_path=section_path,
        ),
        title=_payload_text(payload, "title"),
        document_type=_payload_text(payload, "document_type") or "plain_text",
        collection_item_id=_payload_text(payload, "collection_item_id"),
        source=SourceIdentity(
            connector_id=provider_value,
            provider=provider,
            external_id=external_id,
            url=_payload_text(payload, "source_url"),
        ),
        hierarchy=Hierarchy(
            parent_id=_payload_text(payload, "parent_item_id"),
            ancestor_ids=_payload_strings(payload, "ancestor_ids"),
        ),
        access=EffectiveAccess(),
        citation=CitationInfo(
            section=section_path[-1] if section_path else None,
            section_path=tuple(section_path),
            anchor=_payload_text(payload, "citation_anchor"),
            page_start=_payload_int(payload, "page_start"),
            page_end=_payload_int(payload, "page_end"),
        ),
        relevance_score=score,
    )


def _payload_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _payload_content(payload: Mapping[str, object], key: str) -> str | None:
    """Validate evidence text without changing its bytes-as-text projection."""

    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


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


__all__ = ["VectorSearchIndex"]
