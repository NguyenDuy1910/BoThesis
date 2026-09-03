"""Private Qdrant transport for document_index.ItemIndex.

Not part of document_index's public API. Nothing outside this package should
import from this module; callers use ItemIndex instead.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Iterable
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qmodels

from bothesis.document_index import (
    BM25_MODEL,
    BM25_OPTIONS,
    DENSE_VECTOR_NAME,
    INDEX_SCHEMA_VERSION,
    SPARSE_VECTOR_NAME,
)

log = logging.getLogger(__name__)

_NO_COLLECTION_ID = "__no_collection_id__"
_SEARCH_RETRY_DELAYS = (0.5, 1.0)


class _QdrantBackend:
    """Single Qdrant boundary for connection, filters, and vector CRUD/search."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        collection_name: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        prefer_grpc: bool | None = None,
        timeout: float | None = 60,
        check_compatibility: bool = False,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._url = url
        self._api_key = api_key
        self._prefer_grpc = prefer_grpc
        self._timeout = timeout
        self._check_compatibility = check_compatibility

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self._url:
                raise RuntimeError("Qdrant URL is not configured")
            kwargs: dict[str, Any] = {
                "url": self._url,
                # Preserve the port encoded in the URL. Without this, the
                # Qdrant client defaults to 6333 even for HTTPS deployments.
                "port": None,
                "prefer_grpc": self._prefer_grpc or False,
                "check_compatibility": self._check_compatibility,
            }
            if self._timeout is not None:
                kwargs["timeout"] = self._timeout
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = AsyncQdrantClient(**kwargs)
        return self._client

    @property
    def collection_name(self) -> str:
        if self._collection_name:
            return self._collection_name
        raise RuntimeError("Qdrant collection is not configured")

    async def aclose(self) -> None:
        if self._client is None:
            return
        close = getattr(self._client, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def upsert_points(
        self,
        points: list[Any],
        *,
        collection_name: str | None = None,
    ) -> Any:
        if not points:
            return None
        return await self._maybe_await(
            self.client.upsert(
                collection_name=collection_name or self.collection_name,
                points=points,
            )
        )

    async def replace_item_points(
        self,
        *,
        item_id: str,
        tenant_id: str,
        records: Iterable[Any],
        vectors: Iterable[Iterable[float]],
    ) -> None:
        """Replace one Item's derived records without exposing SDK models."""

        resolved_records = list(records)
        resolved_vectors = [list(vector) for vector in vectors]
        if len(resolved_records) != len(resolved_vectors):
            raise ValueError("every indexed chunk requires one embedding")
        await self.tombstone_item_points(item_id, tenant_id=tenant_id)
        await self.upsert_points(
            [
                qmodels.PointStruct(
                    id=record.point_id,
                    vector={
                        DENSE_VECTOR_NAME: vector,
                        SPARSE_VECTOR_NAME: qmodels.Document(
                            text=record.payload.contextual_text,
                            model=BM25_MODEL,
                            options=BM25_OPTIONS,
                        ),
                    },
                    payload=record.payload.to_payload(),
                )
                for record, vector in zip(
                    resolved_records,
                    resolved_vectors,
                    strict=True,
                )
            ]
        )

    async def search_item_points(
        self,
        *,
        query_vector: list[float],
        query_text: str,
        tenant_id: str,
        collection_item_ids: Iterable[str],
        limit: int,
        candidate_limit: int,
    ) -> list[Any]:
        """Search the private collection within an authorized Item scope."""

        return await self._search(
            query_vector,
            query_text=query_text,
            query_filter=self._access_filter(
                tenant_id=tenant_id,
                collection_item_ids=collection_item_ids,
            ),
            limit=limit,
            candidate_limit=candidate_limit,
        )

    async def get_item_points(
        self,
        *,
        item_id: str,
        tenant_id: str,
        collection_item_id: str,
        chunk_id: str | None,
        limit: int,
    ) -> list[Any]:
        """Load indexed chunks for one authorized Item."""

        access_filter = self._access_filter(
            tenant_id=tenant_id,
            collection_item_ids=(collection_item_id,),
        )
        must = [
            *(access_filter.must or []),
            qmodels.FieldCondition(
                key="item_id",
                match=qmodels.MatchValue(value=item_id),
            ),
        ]
        if chunk_id:
            must.append(
                qmodels.FieldCondition(
                    key="chunk_id",
                    match=qmodels.MatchValue(value=chunk_id),
                )
            )
        points, _ = await self.scroll_points(
            scroll_filter=qmodels.Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return list(points)

    async def set_payload(
        self,
        *,
        payload: dict[str, Any],
        points: Any,
        collection_name: str | None = None,
    ) -> Any:
        return await self._maybe_await(
            self.client.set_payload(
                collection_name=collection_name or self.collection_name,
                payload=payload,
                points=points,
            )
        )

    async def tombstone_item_points(
        self,
        item_id: str,
        *,
        tenant_id: str,
    ) -> Any:
        return await self.set_payload(
            payload={"is_deleted": True},
            points=qmodels.Filter(
                must=[
                qmodels.FieldCondition(
                    key="tenant_id",
                    match=qmodels.MatchValue(value=tenant_id),
                    ),
                    qmodels.FieldCondition(
                        key="item_id",
                        match=qmodels.MatchValue(value=item_id),
                    ),
                ]
            ),
        )

    async def _search(
        self,
        query_vector: list[float],
        *,
        query_text: str,
        query_filter: Any | None,
        limit: int,
        candidate_limit: int,
    ) -> list[Any]:
        """Search dense and BM25 vectors through native reciprocal-rank fusion."""

        if limit < 1 or candidate_limit < limit:
            raise ValueError("candidate_limit must be at least the result limit")

        last_error: Exception | None = None
        for attempt, retry_delay in enumerate((*_SEARCH_RETRY_DELAYS, None), start=1):
            try:
                prefetches = self._build_prefetches(
                    query_vector=query_vector,
                    query_text=query_text,
                    query_filter=query_filter,
                    dense_vector_name=DENSE_VECTOR_NAME,
                    candidate_limit=candidate_limit,
                    sparse_vector_name=SPARSE_VECTOR_NAME,
                )
                if len(prefetches) > 1:
                    result = await self._query_fused_points(
                        collection_name=self.collection_name,
                        prefetches=prefetches,
                        query_filter=query_filter,
                        limit=limit,
                        with_payload=True,
                        with_vectors=False,
                    )
                    return list(getattr(result, "points", []) or [])

                result = await self._query_dense_points(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    dense_vector_name=DENSE_VECTOR_NAME,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
                return list(getattr(result, "points", []) or [])
            except Exception as error:  # noqa: BLE001 - SDK errors vary by transport
                last_error = error
                if retry_delay is None:
                    break
                log.warning(
                    "[%s] Search attempt %d/%d failed; retrying: %s",
                    "item-search",
                    attempt,
                    len(_SEARCH_RETRY_DELAYS) + 1,
                    error,
                )
                await asyncio.sleep(retry_delay)
        raise RuntimeError("Semantic search failed after retries") from last_error

    async def scroll_points(
        self,
        *,
        scroll_filter: Any | None,
        limit: int,
        offset: Any | None = None,
        collection_name: str | None = None,
        with_payload: bool = True,
        with_vectors: bool = False,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "collection_name": collection_name or self.collection_name,
            "scroll_filter": scroll_filter,
            "limit": limit,
            "with_payload": with_payload,
            "with_vectors": with_vectors,
        }
        if offset is not None:
            kwargs["offset"] = offset
        return await self._maybe_await(self.client.scroll(**kwargs))

    @staticmethod
    def _build_prefetches(
        *,
        query_vector: list[float],
        query_text: str | None,
        query_filter: Any | None,
        dense_vector_name: str,
        candidate_limit: int,
        sparse_vector_name: str,
    ) -> list[Any]:
        prefetches: list[Any] = [
            qmodels.Prefetch(
                query=query_vector,
                using=dense_vector_name,
                filter=query_filter,
                limit=candidate_limit,
            )
        ]
        if query_text:
            prefetches.append(
                qmodels.Prefetch(
                    query=qmodels.Document(
                        text=query_text,
                        model=BM25_MODEL,
                        options=BM25_OPTIONS,
                    ),
                    using=sparse_vector_name,
                    filter=query_filter,
                    limit=candidate_limit,
                )
            )
        return prefetches

    async def _query_fused_points(
        self,
        *,
        collection_name: str,
        prefetches: list[Any],
        query_filter: Any | None,
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ) -> Any:
        return await self._maybe_await(
            self.client.query_points(
                collection_name=collection_name,
                prefetch=prefetches,
                query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                limit=limit,
                query_filter=query_filter,
                with_payload=with_payload,
                with_vectors=with_vectors,
            )
        )

    async def _query_dense_points(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        dense_vector_name: str,
        query_filter: Any | None,
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ) -> Any:
        return await self._maybe_await(
            self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                using=dense_vector_name,
                limit=limit,
                query_filter=query_filter,
                with_payload=with_payload,
                with_vectors=with_vectors,
            )
        )

    @staticmethod
    def _access_filter(
        *, tenant_id: str, collection_item_ids: Iterable[str]
    ) -> qmodels.Filter:
        collections = sorted(
            {
                value.strip()
                for value in collection_item_ids
                if isinstance(value, str) and value.strip()
            }
        ) or [_NO_COLLECTION_ID]
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="is_deleted",
                    match=qmodels.MatchValue(value=False),
                ),
                qmodels.FieldCondition(
                    key="schema_version",
                    match=qmodels.MatchValue(value=INDEX_SCHEMA_VERSION),
                ),
                qmodels.FieldCondition(
                    key="tenant_id",
                    match=qmodels.MatchValue(value=tenant_id),
                ),
                qmodels.FieldCondition(
                    key="collection_item_id",
                    match=qmodels.MatchAny(any=collections),
                ),
            ]
        )

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value
