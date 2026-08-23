"""Read-only Qdrant search adapter for contextual document chunks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from bothesis.connector.protocol import (
    BoundingBox,
    CitationInfo,
    CitationSpan,
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


class QdrantSearchIndex:
    """Embed queries, search Qdrant, and rebuild canonical indexed chunks."""

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
        reader_ids: tuple[str, ...],
        connector_ids: tuple[int, ...] | None,
        is_admin: bool,
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
        if connector_ids == ():
            return []

        query_filter = self._store.build_retrieval_filter(
            None,
            access_context=_RetrievalAccess(
                tenant_id=normalized_tenant_id,
                reader_ids=reader_ids,
                is_admin=is_admin,
            ),
            payload_filters=_PayloadFilters(connector_ids=connector_ids),
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
        reader_ids: tuple[str, ...],
        is_admin: bool,
    ) -> None:
        self.tenant_id = tenant_id
        self.reader_ids = reader_ids
        self.space_keys: tuple[str, ...] = ()
        self.is_admin = is_admin


class _PayloadFilters:
    def __init__(self, *, connector_ids: tuple[int, ...] | None) -> None:
        self.connector_ids = connector_ids


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
    provider_value = _payload_text(payload, "provider")
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


__all__ = ["QdrantSearchIndex"]
