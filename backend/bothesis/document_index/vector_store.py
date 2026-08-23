"""Permission-aware Qdrant operations for indexed document chunks.

This module is the only place that knows Qdrant's query and payload models.
Callers must supply an authenticated access context before retrieving content;
missing or incomplete access context deliberately produces a filter that
matches no tenant.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qmodels

from bothesis.document_index import (
    BM25_MODEL,
    BM25_OPTIONS,
    DEFAULT_HYBRID_CANDIDATE_LIMIT,
    DENSE_VECTOR_NAME,
    INDEX_SCHEMA_VERSION,
    SPARSE_VECTOR_NAME,
)
from bothesis.document_index.payload import (
    QdrantChunkPayload,
    QdrantPayloadContext,
)
from bothesis.connector.protocol import (
    CitationInfo,
    CitationSpan,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index.models import ChunkContext, ContextualChunk
from bothesis.db.models import Item

if TYPE_CHECKING:
    from bothesis.services import AuthContext

log = logging.getLogger(__name__)

ACL_FIELD = "reader_ids"
DENIED_ACL_FIELD = "denied_reader_ids"
NO_READER_IDS = "__no_reader_ids__"
_NO_TENANT_ID = "__no_tenant_id__"
_SEARCH_RETRY_DELAYS = (0.5, 1.0)


def acl_match_condition(reader_ids: list[str] | set[str]) -> qmodels.Filter:
    return VectorStore.acl_match_condition(reader_ids)


def no_access_qdrant_condition() -> qmodels.Filter:
    return VectorStore.no_access_condition()


class VectorStoreFilterBuilder:
    # A tuple makes generated filters deterministic, which helps auditing and
    # makes equivalent retrieval requests easier to compare in tests/logs.
    FILTERABLE_LIST_FIELDS: tuple[str, ...] = (
        "provider",
        "document_kind",
        "content_type",
        "item_id",
        "chunk_id",
        "section",
        "external_id",
        "parent_id",
        "root_id",
        "ancestor_ids",
        "connector_id",
    )

    @classmethod
    def build_request_filter(cls, request: Any) -> qmodels.Filter:
        return VectorStore.build_retrieval_filter(
            None,
            access_context=getattr(request, "access", None),
            payload_filters=getattr(request, "filters", None),
        )

    @classmethod
    def business_conditions(
        cls,
        filters: Any,
        *,
        field_map: dict[str, str] | None = None,
    ) -> list[Any]:
        conditions: list[Any] = []
        resolved_field_map = {"section": "citation_section", **(field_map or {})}
        for logical_name in cls.FILTERABLE_LIST_FIELDS:
            values = getattr(filters, logical_name, [])
            if not values and logical_name == "connector_id":
                values = getattr(filters, "connector_ids", [])
            if not values:
                continue
            qdrant_field = resolved_field_map.get(logical_name, logical_name)
            conditions.append(
                qmodels.FieldCondition(
                    key=qdrant_field,
                    match=qmodels.MatchAny(any=values),
                )
            )
        return conditions


class VectorStore:
    """Single Qdrant boundary for connection, filters, and vector CRUD/search."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        collection_name: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        prefer_grpc: bool | None = None,
        timeout: int | float | None = 60,
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

    async def set_document_payload(
        self,
        document_id: str,
        payload: dict[str, Any],
        *,
        document_id_field: str = "item_id",
        collection_name: str | None = None,
    ) -> Any:
        return await self.set_payload(
            collection_name=collection_name,
            payload=payload,
            points=self.document_filter(
                document_id, document_id_field=document_id_field
            ),
        )

    async def sync_document_acl(
        self,
        document_id: str,
        acl: Mapping[str, int] | Iterable[str],
        *,
        denied_reader_ids: Iterable[str] = (),
        acl_field: str = ACL_FIELD,
        document_id_field: str = "item_id",
        collection_name: str | None = None,
    ) -> Any:
        raw_reader_ids = acl.keys() if isinstance(acl, Mapping) else acl
        reader_ids = self._normalise_reader_ids(raw_reader_ids)
        denied = self._normalise_reader_ids(denied_reader_ids)
        return await self.set_document_payload(
            document_id,
            {acl_field: reader_ids, DENIED_ACL_FIELD: denied},
            document_id_field=document_id_field,
            collection_name=collection_name,
        )

    async def soft_delete_document_points(
        self,
        document_id: str,
        *,
        document_id_field: str = "item_id",
        is_deleted_field: str = "is_deleted",
        acl_field: str = ACL_FIELD,
        collection_name: str | None = None,
    ) -> Any:
        return await self.set_document_payload(
            document_id,
            {is_deleted_field: True, acl_field: [], DENIED_ACL_FIELD: []},
            document_id_field=document_id_field,
            collection_name=collection_name,
        )

    async def semantic_search(
        self,
        query_vector: list[float],
        *,
        query_text: str | None = None,
        query_filter: Any | None,
        limit: int,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
        dense_vector_name: str = DENSE_VECTOR_NAME,
        sparse_vector_name: str = SPARSE_VECTOR_NAME,
        collection_name: str | None = None,
        with_payload: bool = True,
        with_vectors: bool = False,
        log_label: str = "vector-search",
    ) -> list[Any]:
        """Search dense and BM25 vectors through native reciprocal-rank fusion."""

        if limit < 1 or candidate_limit < limit:
            raise ValueError("candidate_limit must be at least the result limit")

        last_error: Exception | None = None
        resolved_collection = collection_name or self.collection_name
        for attempt, retry_delay in enumerate((*_SEARCH_RETRY_DELAYS, None), start=1):
            try:
                prefetches = self._build_prefetches(
                    query_vector=query_vector,
                    query_text=query_text,
                    query_filter=query_filter,
                    dense_vector_name=dense_vector_name,
                    candidate_limit=candidate_limit,
                    sparse_vector_name=sparse_vector_name,
                )
                if len(prefetches) > 1:
                    result = await self._query_fused_points(
                        collection_name=resolved_collection,
                        prefetches=prefetches,
                        query_filter=query_filter,
                        limit=limit,
                        with_payload=with_payload,
                        with_vectors=with_vectors,
                    )
                    return list(getattr(result, "points", []) or [])

                result = await self._query_dense_points(
                    collection_name=resolved_collection,
                    query_vector=query_vector,
                    dense_vector_name=dense_vector_name,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=with_payload,
                    with_vectors=with_vectors,
                )
                return list(getattr(result, "points", []) or [])
            except Exception as error:
                last_error = error
                if retry_delay is None:
                    break
                log.warning(
                    "[%s] Search attempt %d/%d failed; retrying: %s",
                    log_label,
                    attempt,
                    len(_SEARCH_RETRY_DELAYS) + 1,
                    error,
                )
                await asyncio.sleep(retry_delay)
        raise RuntimeError("Semantic search failed after retries") from last_error

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

    async def count_points(
        self,
        *,
        count_filter: Any | None,
        collection_name: str | None = None,
    ) -> int:
        result = await self._maybe_await(
            self.client.count(
                collection_name=collection_name or self.collection_name,
                count_filter=count_filter,
            )
        )
        return int(getattr(result, "count", 0) or 0)

    async def keyword_scroll(
        self,
        query_text: str,
        *,
        base_filter: Any | None = None,
        content_field: str = "chunk_text",
        limit: int = 100,
        collection_name: str | None = None,
    ) -> Any:
        must = [
            qmodels.FieldCondition(
                key=content_field,
                match=qmodels.MatchText(text=query_text),
            ),
            *self._filter_must(base_filter),
        ]
        return await self.scroll_points(
            collection_name=collection_name,
            scroll_filter=qmodels.Filter(
                must=must, should=self._filter_should(base_filter)
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

    async def scroll_document_points(
        self,
        document_id: str,
        *,
        limit: int,
        offset: Any | None = None,
        include_deleted: bool = False,
        document_id_field: str = "item_id",
        is_deleted_field: str = "is_deleted",
        collection_name: str | None = None,
    ) -> Any:
        must: list[Any] = [
            qmodels.FieldCondition(
                key=document_id_field,
                match=qmodels.MatchValue(value=document_id),
            )
        ]
        if not include_deleted:
            must.append(
                qmodels.FieldCondition(
                    key=is_deleted_field,
                    match=qmodels.MatchValue(value=False),
                )
            )
        return await self.scroll_points(
            collection_name=collection_name,
            scroll_filter=qmodels.Filter(must=must),
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

    async def scroll_sibling_points(
        self,
        document_id: str,
        *,
        base_filter: Any | None = None,
        limit: int = 10,
        document_id_field: str = "item_id",
        is_deleted_field: str = "is_deleted",
        collection_name: str | None = None,
    ) -> Any:
        must = self._document_context_must(
            document_id,
            base_filter=base_filter,
            document_id_field=document_id_field,
            is_deleted_field=is_deleted_field,
        )
        return await self.scroll_points(
            collection_name=collection_name,
            scroll_filter=qmodels.Filter(
                must=must,
                should=self._filter_should(base_filter),
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

    async def scroll_position_window_points(
        self,
        document_id: str,
        chunk_position: int,
        *,
        window: int = 2,
        limit: int | None = None,
        base_filter: Any | None = None,
        document_id_field: str = "item_id",
        is_deleted_field: str = "is_deleted",
        chunk_index_field: str = "chunk_index",
        collection_name: str | None = None,
    ) -> Any:
        must = self._document_context_must(
            document_id,
            base_filter=base_filter,
            document_id_field=document_id_field,
            is_deleted_field=is_deleted_field,
        )
        must.append(
            qmodels.FieldCondition(
                    key=chunk_index_field,
                range=qmodels.Range(
                    gte=chunk_position - window,
                    lte=chunk_position + window,
                ),
            )
        )
        return await self.scroll_points(
            collection_name=collection_name,
            scroll_filter=qmodels.Filter(
                must=must,
                should=self._filter_should(base_filter),
            ),
            limit=limit or window * 2 + 1,
            with_payload=True,
            with_vectors=False,
        )

    async def scroll_chunk_kind_points(
        self,
        document_id: str,
        kinds: list[str],
        *,
        base_filter: Any | None = None,
        limit: int = 5,
        document_id_field: str = "item_id",
        is_deleted_field: str = "is_deleted",
        chunk_kind_field: str = "document_kind",
        collection_name: str | None = None,
    ) -> Any:
        must = self._document_context_must(
            document_id,
            base_filter=base_filter,
            document_id_field=document_id_field,
            is_deleted_field=is_deleted_field,
        )
        must.append(
            qmodels.FieldCondition(
                key=chunk_kind_field,
                match=qmodels.MatchAny(any=kinds),
            )
        )
        return await self.scroll_points(
            collection_name=collection_name,
            scroll_filter=qmodels.Filter(
                must=must,
                should=self._filter_should(base_filter),
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

    async def scroll_hierarchy_related_points(
        self,
        document_id: str,
        *,
        hierarchy_node_id: int | None = None,
        ancestor_node_id: int | None = None,
        base_filter: Any | None = None,
        limit: int = 8,
        document_id_field: str = "item_id",
        is_deleted_field: str = "is_deleted",
        hierarchy_node_id_field: str = "parent_id",
        ancestor_ids_field: str = "ancestor_ids",
        collection_name: str | None = None,
    ) -> Any:
        if hierarchy_node_id is None and ancestor_node_id is None:
            return [], None
        must = self._filter_must(base_filter)
        must.append(
            qmodels.FieldCondition(
                key=is_deleted_field,
                match=qmodels.MatchValue(value=False),
            )
        )
        if hierarchy_node_id is not None:
            must.append(
                qmodels.FieldCondition(
                    key=hierarchy_node_id_field,
                    match=qmodels.MatchValue(value=hierarchy_node_id),
                )
            )
        else:
            must.append(
                qmodels.FieldCondition(
                    key=ancestor_ids_field,
                    match=qmodels.MatchValue(value=ancestor_node_id),
                )
            )
        return await self.scroll_points(
            collection_name=collection_name,
            scroll_filter=qmodels.Filter(
                must=must,
                must_not=[
                    qmodels.FieldCondition(
                        key=document_id_field,
                        match=qmodels.MatchValue(value=document_id),
                    )
                ],
                should=self._filter_should(base_filter),
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

    @classmethod
    def build_retrieval_filter(
        cls,
        search_params: Any | None,
        *,
        access_context: Any | None = None,
        payload_filters: Any | None = None,
        is_deleted_field: str = "is_deleted",
        tenant_id_field: str = "tenant_id",
        document_id_field: str = "item_id",
        source_type_field: str = "provider",
        space_key_field: str = "parent_id",
        ancestor_ids_field: str = "ancestor_ids",
    ) -> qmodels.Filter:
        tenant_id = getattr(access_context, "tenant_id", None)
        if isinstance(tenant_id, str) and tenant_id.strip():
            conditions = cls.access_conditions(
                tenant_id=tenant_id,
                reader_ids=getattr(access_context, "reader_ids", []),
                space_keys=getattr(access_context, "space_keys", []),
                is_admin=getattr(access_context, "is_admin", False) is True,
                is_deleted_field=is_deleted_field,
                tenant_id_field=tenant_id_field,
            )
        else:
            log.warning(
                "VectorStore.build_retrieval_filter: missing tenant access context; "
                "denying all"
            )
            conditions = cls._deny_all_conditions(
                is_deleted_field=is_deleted_field,
                tenant_id_field=tenant_id_field,
            )

        conditions.extend(
            VectorStoreFilterBuilder.business_conditions(
                payload_filters,
                field_map={
                    "item_id": document_id_field,
                    "provider": source_type_field,
                    "connector_id": "connector_id",
                },
            )
        )
        conditions.extend(
            cls._search_param_conditions(
                search_params,
                source_type_field=source_type_field,
                space_key_field=space_key_field,
                ancestor_ids_field=ancestor_ids_field,
            )
        )

        return qmodels.Filter(must=conditions)

    @classmethod
    def build_lifecycle_filter(
        cls,
        *,
        is_deleted_field: str = "is_deleted",
    ) -> qmodels.Filter:
        """Exclude tombstones when a caller applies no access-scope filter."""

        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key=is_deleted_field,
                    match=qmodels.MatchValue(value=False),
                ),
                cls._schema_condition(),
            ]
        )

    @classmethod
    def build_access_filter(
        cls,
        *,
        tenant_id: str,
        reader_ids: list[str] | set[str] | None = None,
        space_keys: list[str] | set[str] | None = None,
        is_admin: bool = True,
        is_deleted_field: str = "is_deleted",
        tenant_id_field: str = "tenant_id",
    ) -> qmodels.Filter:
        return qmodels.Filter(
            must=cls.access_conditions(
                tenant_id=tenant_id,
                reader_ids=reader_ids or [],
                space_keys=space_keys or [],
                is_admin=is_admin,
                is_deleted_field=is_deleted_field,
                tenant_id_field=tenant_id_field,
            )
        )

    @classmethod
    def build_search_params_filter(
        cls,
        params: Any | None,
        *,
        source_type_field: str = "provider",
        space_key_field: str = "parent_id",
        ancestor_ids_field: str = "ancestor_ids",
    ) -> qmodels.Filter | None:
        conditions = cls._search_param_conditions(
            params,
            source_type_field=source_type_field,
            space_key_field=space_key_field,
            ancestor_ids_field=ancestor_ids_field,
        )
        if not conditions:
            return None
        return qmodels.Filter(must=conditions)

    @classmethod
    def access_conditions(
        cls,
        *,
        tenant_id: str,
        reader_ids: Iterable[str],
        space_keys: Iterable[str] | None = None,
        is_admin: bool = True,
        is_deleted_field: str = "is_deleted",
        tenant_id_field: str = "tenant_id",
    ) -> list[Any]:
        if not tenant_id.strip():
            return cls._deny_all_conditions(
                is_deleted_field=is_deleted_field,
                tenant_id_field=tenant_id_field,
            )
        conditions: list[Any] = [
            qmodels.FieldCondition(
                key=is_deleted_field,
                match=qmodels.MatchValue(value=False),
            ),
            cls._schema_condition(),
            qmodels.FieldCondition(
                key=tenant_id_field,
                match=qmodels.MatchValue(value=tenant_id),
            ),
        ]
        if not is_admin:
            all_ids = cls._normalise_reader_ids(
                [*(reader_ids or []), *(space_keys or [])]
            )
            conditions.append(cls.acl_match_condition(all_ids))
        return conditions

    @staticmethod
    def document_filter(
        document_id: str,
        *,
        document_id_field: str = "item_id",
    ) -> qmodels.Filter:
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key=document_id_field,
                    match=qmodels.MatchValue(value=document_id),
                )
            ]
        )

    @classmethod
    def acl_match_condition(cls, reader_ids: Iterable[str]) -> qmodels.Filter:
        ids = cls._normalise_reader_ids(reader_ids)
        if not ids:
            ids = [NO_READER_IDS]
        return qmodels.Filter(
            should=[
                qmodels.FieldCondition(
                    key=ACL_FIELD,
                    match=qmodels.MatchAny(any=ids),
                ),
            ],
            must_not=[
                qmodels.FieldCondition(
                    key=DENIED_ACL_FIELD,
                    match=qmodels.MatchAny(any=ids),
                )
            ],
        )

    @classmethod
    def no_access_condition(cls) -> qmodels.Filter:
        return cls.acl_match_condition({NO_READER_IDS})

    @classmethod
    def build_reader_ids_filter(
        cls,
        reader_ids: Iterable[str],
    ) -> qmodels.Filter:
        return qmodels.Filter(must=[cls.acl_match_condition(reader_ids)])

    @staticmethod
    def _search_param_conditions(
        params: Any | None,
        *,
        source_type_field: str,
        space_key_field: str,
        ancestor_ids_field: str,
    ) -> list[Any]:
        conditions: list[Any] = []
        provider = getattr(params, "provider", None)
        if provider:
            conditions.append(
                qmodels.FieldCondition(
                    key=source_type_field,
                    match=qmodels.MatchValue(value=provider),
                )
            )
        parent_id = getattr(params, "parent_id", None)
        if parent_id:
            conditions.append(
                qmodels.FieldCondition(
                    key=space_key_field,
                    match=qmodels.MatchValue(value=parent_id),
                )
            )
        ancestor_id = getattr(params, "ancestor_id", None)
        if ancestor_id is not None:
            conditions.append(
                qmodels.FieldCondition(
                    key=ancestor_ids_field,
                    match=qmodels.MatchValue(value=ancestor_id),
                )
            )
        return conditions

    @classmethod
    def _deny_all_conditions(
        cls,
        *,
        is_deleted_field: str,
        tenant_id_field: str,
    ) -> list[Any]:
        return [
            qmodels.FieldCondition(
                key=is_deleted_field,
                match=qmodels.MatchValue(value=False),
            ),
            cls._schema_condition(),
            qmodels.FieldCondition(
                key=tenant_id_field,
                match=qmodels.MatchValue(value=_NO_TENANT_ID),
            ),
            cls.no_access_condition(),
        ]

    @staticmethod
    def _schema_condition() -> qmodels.FieldCondition:
        return qmodels.FieldCondition(
            key="schema_version",
            match=qmodels.MatchValue(value=INDEX_SCHEMA_VERSION),
        )

    @staticmethod
    def _normalise_reader_ids(reader_ids: Iterable[str]) -> list[str]:
        return sorted(
            {
                reader_id
                for reader_id in reader_ids
                if isinstance(reader_id, str)
                and reader_id
                and reader_id != NO_READER_IDS
            }
        )

    @classmethod
    def _document_context_must(
        cls,
        document_id: str,
        *,
        base_filter: Any | None,
        document_id_field: str,
        is_deleted_field: str,
    ) -> list[Any]:
        must = cls._filter_must(base_filter)
        must.extend(
            [
                qmodels.FieldCondition(
                    key=document_id_field,
                    match=qmodels.MatchValue(value=document_id),
                ),
                qmodels.FieldCondition(
                    key=is_deleted_field,
                    match=qmodels.MatchValue(value=False),
                ),
            ]
        )
        return must

    @staticmethod
    def _filter_must(base_filter: Any | None) -> list[Any]:
        if base_filter is None:
            return []
        return list(getattr(base_filter, "must", None) or [])

    @staticmethod
    def _filter_should(base_filter: Any | None) -> list[Any] | None:
        if base_filter is None:
            return None
        should = getattr(base_filter, "should", None)
        return list(should) if should else None

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value


class QdrantDocumentIndex:
    """Store processing output directly in the derived Qdrant index."""

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
        access: AuthContext,
        embedding_model: str,
        source_fingerprint: str,
    ) -> None:
        if access.tenant_id is None:
            raise ValueError("indexed chat documents require an active tenant")
        if len(chunks) != len(vectors) or not chunks:
            raise ValueError("every canonical chunk requires one embedding")

        await self._store.soft_delete_document_points(str(document.id))
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if chunk.item_id != str(document.id):
                raise ValueError("contextual chunk belongs to a different document")
            payload = QdrantChunkPayload.from_contextual_chunk(
                chunk,
                QdrantPayloadContext(
                    tenant_id=str(access.tenant_id),
                    connector_id="upload",
                    scope_id=(
                        str(document.connector_scope_id)
                        if document.connector_scope_id
                        else None
                    ),
                    embedding_model=embedding_model,
                ),
            ).for_qdrant()
            points.append(
                qmodels.PointStruct(
                    id=_document_point_id(document.id, chunk.chunk_index),
                    vector={
                        DENSE_VECTOR_NAME: list(vector),
                        SPARSE_VECTOR_NAME: qmodels.Document(
                            text=chunk.contextual_text,
                            model=BM25_MODEL,
                            options=BM25_OPTIONS,
                        ),
                    },
                    payload=payload,
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
            reader_ids={str(access.user_id)},
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
        chunks: list[ContextualChunk] = []
        for point in points:
            payload = getattr(point, "payload", None)
            if not isinstance(payload, dict):
                continue
            content = payload.get("chunk_text")
            if not isinstance(content, str) or not content.strip():
                continue
            raw_score = getattr(point, "score", None)
            score = float(raw_score) if isinstance(raw_score, (int, float)) else None
            chunk_id = str(
                payload.get("chunk_id")
                or f"{document.id}:{int(payload.get('chunk_index') or 0)}"
            )
            source = SourceIdentity(
                connector_id=str(payload.get("connector_id") or "upload"),
                provider=SourceProvider.FILE,
                external_id=str(payload.get("external_id") or document.id),
                url=(
                    str(payload["source_url"])
                    if payload.get("source_url") is not None
                    else None
                ),
            )
            chunks.append(
                ContextualChunk(
                    id=chunk_id,
                    item_id=str(document.id),
                    chunk_index=int(payload.get("chunk_index") or 0),
                    content_type=str(payload.get("content_type") or "text"),
                    chunk_text=content,
                    contextual_text=str(payload.get("contextual_text") or content),
                    context=ChunkContext(
                        section_path=_payload_strings(payload, "context_section_path"),
                        summary=_payload_text(payload, "context_summary"),
                    ),
                    title=str(payload.get("title") or document.title or document.id),
                    document_kind=str(payload.get("document_kind") or "document"),
                    source=source,
                    hierarchy=Hierarchy(
                        parent_id=_payload_text(payload, "parent_id"),
                        root_id=_payload_text(payload, "root_id"),
                        ancestor_ids=_payload_strings(payload, "ancestor_ids"),
                    ),
                    access=EffectiveAccess(
                        reader_ids=_payload_strings(payload, "reader_ids"),
                    ),
                    citation=_citation_from_payload(payload),
                    relevance_score=score,
                )
            )
        return tuple(chunks)

    async def update_document_access(
        self,
        document_id: UUID,
        *,
        access: AuthContext,
    ) -> None:
        if access.tenant_id is None:
            raise ValueError("indexed chat documents require an active tenant")
        await self._store.set_document_payload(
            str(document_id),
            {
                "tenant_id": str(access.tenant_id),
                "reader_ids": [str(access.user_id)],
            },
        )

    async def soft_delete_document(self, document_id: UUID) -> None:
        await self._store.soft_delete_document_points(str(document_id))

    async def aclose(self) -> None:
        await self._store.aclose()


def _document_point_id(document_id: UUID, chunk_index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"bothesis:document:{document_id}:{chunk_index}"))


def _citation_from_payload(payload: dict[str, Any]) -> CitationInfo:
    return CitationInfo(
        section=_payload_text(payload, "citation_section"),
        section_path=tuple(_payload_strings(payload, "citation_section_path")),
        anchor=_payload_text(payload, "citation_anchor"),
        spans=tuple(_payload_citation_spans(payload.get("citation_spans"))),
    )


def _payload_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _payload_strings(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _payload_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _payload_bbox(value: object) -> Any:
    from bothesis.connector.protocol import BoundingBox

    if not isinstance(value, Mapping):
        return None
    try:
        return BoundingBox.model_validate(value)
    except ValueError:
        return None


def _payload_citation_spans(value: object) -> list[CitationSpan]:
    if not isinstance(value, (list, tuple)):
        return []
    spans: list[CitationSpan] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        try:
            spans.append(
                CitationSpan(
                    page=_payload_int(raw, "page"),
                    element_id=_payload_text(raw, "element_id"),
                    start_offset=_payload_int(raw, "start_offset"),
                    end_offset=_payload_int(raw, "end_offset"),
                    bounding_box=_payload_bbox(raw.get("bounding_box")),
                )
            )
        except ValueError:
            continue
    return spans
