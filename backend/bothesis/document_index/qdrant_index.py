"""Document-index projection built on the generic Qdrant store."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from qdrant_client import models as qmodels

from bothesis.db.models import Item
from bothesis.document_index import (
    BM25_MODEL,
    BM25_OPTIONS,
    DEFAULT_HYBRID_CANDIDATE_LIMIT,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    IndexedChunkRecord,
    IndexingContext,
    contextual_chunk_from_point,
)
from bothesis.document_index.models import ContextualChunk

if TYPE_CHECKING:
    from bothesis.document_index.vector_store import VectorStore
    from bothesis.services import AuthContext


class QdrantDocumentIndex:
    """Project contextual chunks into the derived Qdrant index."""

    def __init__(
        self,
        store: VectorStore,
        *,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least one")
        self._store = store
        self._candidate_limit = candidate_limit

    async def replace_document(
        self,
        document: Item,
        chunks: Sequence[ContextualChunk],
        vectors: Sequence[Sequence[float]],
        *,
        context: IndexingContext,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("every canonical chunk requires one embedding")

        await self._store.soft_delete_document_points(
            str(document.id),
            tenant_id=context.tenant_id,
        )
        points: list[qmodels.PointStruct] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if chunk.item_id != str(document.id):
                raise ValueError("contextual chunk belongs to a different document")
            record = IndexedChunkRecord.from_contextual_chunk(chunk, context)
            points.append(
                qmodels.PointStruct(
                    id=record.point_id,
                    vector={
                        DENSE_VECTOR_NAME: list(vector),
                        SPARSE_VECTOR_NAME: qmodels.Document(
                            text=chunk.contextual_text,
                            model=BM25_MODEL,
                            options=BM25_OPTIONS,
                        ),
                    },
                    payload=record.payload.to_payload(),
                )
            )
        await self._store.upsert_points(points)

    async def search_document(
        self,
        document: Item,
        query: str,
        query_vector: list[float],
        *,
        access: AuthContext,
        limit: int,
    ) -> tuple[ContextualChunk, ...]:
        if access.tenant_id is None:
            return ()
        base_filter = self._store.build_access_filter(
            tenant_id=str(access.tenant_id),
            collection_item_ids={str(document.parent_item_id)},
        )
        query_filter = qmodels.Filter(
            must=[
                *(base_filter.must or []),
                qmodels.FieldCondition(
                    key="item_id",
                    match=qmodels.MatchValue(value=str(document.id)),
                ),
            ]
        )
        points = await self._store.semantic_search(
            query_vector,
            query_text=query.strip(),
            query_filter=query_filter,
            limit=limit,
            candidate_limit=max(limit, self._candidate_limit),
            log_label="uploaded-document-search",
        )
        return tuple(
            chunk
            for point in points
            if (chunk := contextual_chunk_from_point(point)) is not None
        )

    async def update_document_access(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> None:
        if access.tenant_id is None:
            raise ValueError("indexed chat documents require an active tenant")
        # Durable Collection grants live in PostgreSQL and are never projected
        # into Qdrant, so grant changes require no point rewrite.
        del document_id

    async def soft_delete_document(
        self,
        document_id: UUID,
        *,
        tenant_id: str | None = None,
    ) -> None:
        await self._store.soft_delete_document_points(
            str(document_id),
            tenant_id=tenant_id,
        )

    async def aclose(self) -> None:
        await self._store.aclose()


__all__ = ["QdrantDocumentIndex"]
