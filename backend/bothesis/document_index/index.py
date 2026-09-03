"""The single public capability for indexing, searching, and removing Item content."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from bothesis.connector.protocol import Chunk, DocumentItem
from bothesis.document_index import (
    DEFAULT_HYBRID_CANDIDATE_LIMIT,
    INDEX_SCHEMA_VERSION,
    ChunkContextGenerator,
    ContextualChunk,
    EmbeddingService,
    IndexingContext,
)
from bothesis.document_index._qdrant import _QdrantBackend
from bothesis.document_index.payload import (
    _contextual_chunk_from_point,
    build_index_records,
)


class ItemIndex:
    """Index, search, and remove Item content in the derived vector index."""

    def __init__(
        self,
        *,
        backend: _QdrantBackend | None = None,
        collection_name: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        prefer_grpc: bool | None = None,
        timeout: float | None = 60,
        embedder: EmbeddingService | None = None,
        semantic_contextualizer: ChunkContextGenerator | None = None,
        embedding_batch_size: int = 32,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
    ) -> None:
        if embedding_batch_size < 1:
            raise ValueError("embedding_batch_size must be at least one")
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least one")
        self._backend = backend or _QdrantBackend(
            collection_name=collection_name,
            url=url,
            api_key=api_key,
            prefer_grpc=prefer_grpc,
            timeout=timeout,
        )
        self._embedder = embedder
        self._semantic_contextualizer = semantic_contextualizer
        self._embedding_batch_size = embedding_batch_size
        self._candidate_limit = candidate_limit

    async def index_item_content(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        context: IndexingContext,
    ) -> int:
        """Contextualize, embed, and replace all indexed content for one Item."""

        embedder = self._require_embedder()
        records = await build_index_records(
            chunks,
            item,
            context,
            semantic_contextualizer=self._semantic_contextualizer,
        )
        texts = [record.payload.contextual_text for record in records]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._embedding_batch_size):
            vectors.extend(
                await embedder.embed_documents(
                    texts[start : start + self._embedding_batch_size]
                )
            )
        if len(vectors) != len(records) or any(not vector for vector in vectors):
            raise ValueError("every contextual chunk requires one embedding")

        await self._backend.replace_item_points(
            item_id=item.id,
            tenant_id=context.tenant_id,
            records=records,
            vectors=vectors,
        )
        return len(records)

    async def search_item_content(
        self,
        query: str,
        *,
        limit: int,
        tenant_id: str,
        collection_item_ids: tuple[str, ...],
    ) -> list[ContextualChunk]:
        """Return indexed chunks after applying lifecycle and access scope filters."""

        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least one")
        normalized_tenant_id = tenant_id.strip() if isinstance(tenant_id, str) else ""
        if not normalized_tenant_id:
            raise ValueError("tenant_id must not be empty")
        if not collection_item_ids:
            return []

        query_vector = await self._require_embedder().embed_query(normalized_query)
        points = await self._backend.search_item_points(
            query_vector=query_vector,
            query_text=normalized_query,
            tenant_id=normalized_tenant_id,
            collection_item_ids=collection_item_ids,
            limit=limit,
            candidate_limit=max(limit, self._candidate_limit),
        )
        return _normalise_points(points)

    async def get_item_content(
        self,
        item_id: str,
        *,
        tenant_id: str,
        collection_item_id: str,
        chunk_id: str | None = None,
        limit: int = 100,
    ) -> list[ContextualChunk]:
        """Return indexed chunks for one Item, ordered by source position."""

        normalized_item_id = _required_text(item_id, "item_id")
        normalized_tenant_id = _required_text(tenant_id, "tenant_id")
        normalized_collection_id = _required_text(
            collection_item_id, "collection_item_id"
        )
        if limit < 1:
            raise ValueError("limit must be at least one")

        points = await self._backend.get_item_points(
            item_id=normalized_item_id,
            tenant_id=normalized_tenant_id,
            collection_item_id=normalized_collection_id,
            chunk_id=chunk_id,
            limit=limit,
        )
        return sorted(_normalise_points(points), key=lambda chunk: chunk.chunk_index)

    async def remove_item_content(
        self,
        item_id: str,
        *,
        tenant_id: str,
    ) -> None:
        """Tombstone all indexed content for one Item."""

        await self._backend.tombstone_item_points(
            _required_text(item_id, "item_id"),
            tenant_id=_required_text(tenant_id, "tenant_id"),
        )

    async def aclose(self) -> None:
        for dependency in (self._embedder, self._backend):
            if dependency is None:
                continue
            close = getattr(dependency, "aclose", None)
            if close is not None:
                await close()

    def current_processing_signature(self) -> dict[str, Any]:
        """Report this index's own embedding/contextualization/schema versions.

        Callers use this to decide whether previously indexed content is still
        current, without document_index owning that decision itself.
        """

        return {
            "embedding_model": self._require_embedder().embedding_model,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "contextualization_enabled": self._semantic_contextualizer is not None,
            "contextualization_model": (
                self._semantic_contextualizer.model_name
                if self._semantic_contextualizer is not None
                else None
            ),
        }

    def _require_embedder(self) -> EmbeddingService:
        if self._embedder is None:
            raise RuntimeError("Item content embedding is not configured")
        return self._embedder


def _normalise_points(points: Sequence[object]) -> list[ContextualChunk]:
    chunks: list[ContextualChunk] = []
    seen_ids: set[str] = set()
    for point in points:
        chunk = _contextual_chunk_from_point(point)
        if chunk is None or chunk.id in seen_ids:
            continue
        seen_ids.add(chunk.id)
        chunks.append(chunk)
    return chunks


def _required_text(value: str, field: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


__all__ = ["ItemIndex"]
