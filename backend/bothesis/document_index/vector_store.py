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
import os
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from qdrant_client import AsyncQdrantClient, models as qmodels

log = logging.getLogger(__name__)

ACL_FIELD = "access_control_list"
NO_READER_IDS = "__no_reader_ids__"
_NO_TENANT_ID = "__no_tenant_id__"
_SEARCH_RETRY_DELAYS = (0.5, 1.0)


class QdrantSettings(Protocol):
    """The small configuration contract required by :class:`VectorStore`."""

    qdrant_url: str
    qdrant_collection: str
    qdrant_api_key: str | None
    qdrant_prefer_grpc: bool


def _required_environment_value(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _qdrant_json_path_segment(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def acl_match_condition(reader_ids: list[str] | set[str]) -> qmodels.Filter:
    return VectorStore.acl_match_condition(reader_ids)


def no_access_qdrant_condition() -> qmodels.Filter:
    return VectorStore.no_access_condition()


class VectorStoreFilterBuilder:
    FILTER_FIELD_MAP: dict[str, str] = {
        "source_type": "source_type",
        "doc_id": "document_id",
    }

    # A tuple makes generated filters deterministic, which helps auditing and
    # makes equivalent retrieval requests easier to compare in tests/logs.
    FILTERABLE_LIST_FIELDS: tuple[str, ...] = (
        "source_system",
        "doc_type",
        "domains",
        "project_key",
        "space_key",
        "ticket_status",
        "ticket_type",
        "source_type",
        "content_type",
        "chunk_kind",
        "language",
        "doc_id",
        "section_id",
        "external_id",
        "parent_content_id",
        "attachment_id",
        "comment_id",
        "sheet_name",
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
        resolved_field_map = {**cls.FILTER_FIELD_MAP, **(field_map or {})}
        for logical_name in cls.FILTERABLE_LIST_FIELDS:
            values = getattr(filters, logical_name, [])
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

    @classmethod
    def from_settings(
        cls,
        config: QdrantSettings,
        *,
        timeout: int | float | None = 60,
    ) -> VectorStore:
        """Create a store from an application-owned configuration object.

        Configuration stays at the composition boundary. This module does not
        read environment variables or depend on a project-wide settings
        singleton.
        """

        return cls(
            collection_name=config.qdrant_collection,
            url=config.qdrant_url,
            api_key=config.qdrant_api_key,
            prefer_grpc=config.qdrant_prefer_grpc,
            timeout=timeout,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        timeout: int | float | None = 60,
    ) -> VectorStore:
        """Create a store from the backend's Qdrant environment variables."""

        return cls(
            collection_name=_required_environment_value("QDRANT_COLLECTION"),
            url=_required_environment_value("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            prefer_grpc=os.getenv("QDRANT_PREFER_GRPC") == "true",
            timeout=timeout,
        )

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
            log.info(
                "Configured Qdrant vector store: grpc=%s, collection=%s",
                kwargs["prefer_grpc"],
                self.collection_name,
            )
        return self._client

    @property
    def collection_name(self) -> str:
        if self._collection_name:
            return self._collection_name
        raise RuntimeError("Qdrant collection is not configured")

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
        document_id_field: str = "document_id",
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
        acl_field: str = ACL_FIELD,
        document_id_field: str = "document_id",
        collection_name: str | None = None,
    ) -> Any:
        raw_reader_ids = acl.keys() if isinstance(acl, Mapping) else acl
        reader_ids = self._normalise_reader_ids(raw_reader_ids)
        return await self.set_document_payload(
            document_id,
            {acl_field: reader_ids},
            document_id_field=document_id_field,
            collection_name=collection_name,
        )

    async def soft_delete_document_points(
        self,
        document_id: str,
        *,
        document_id_field: str = "document_id",
        is_deleted_field: str = "is_deleted",
        acl_field: str = ACL_FIELD,
        collection_name: str | None = None,
    ) -> Any:
        return await self.set_document_payload(
            document_id,
            {is_deleted_field: True, acl_field: []},
            document_id_field=document_id_field,
            collection_name=collection_name,
        )

    async def semantic_search(
        self,
        query_vector: list[float],
        *,
        query_filter: Any | None,
        limit: int,
        dense_vector_name: str = "content",
        title_vector_name: str | None = "title",
        title_limit: int | None = None,
        sparse_vector: dict[str, list] | None = None,
        sparse_vector_name: str = "bm25",
        sparse_limit: int | None = None,
        collection_name: str | None = None,
        with_payload: bool = True,
        with_vectors: bool = False,
        log_label: str = "vector-search",
    ) -> list[Any]:
        """Search dense vectors, using reciprocal-rank fusion when available."""

        last_error: Exception | None = None
        resolved_collection = collection_name or self.collection_name
        for attempt, retry_delay in enumerate((*_SEARCH_RETRY_DELAYS, None), start=1):
            try:
                prefetches = self._build_prefetches(
                    query_vector=query_vector,
                    dense_vector_name=dense_vector_name,
                    limit=limit,
                    title_vector_name=title_vector_name,
                    title_limit=title_limit,
                    sparse_vector=sparse_vector,
                    sparse_vector_name=sparse_vector_name,
                    sparse_limit=sparse_limit,
                )
                if len(prefetches) > 1:
                    try:
                        result = await self._query_fused_points(
                            collection_name=resolved_collection,
                            prefetches=prefetches,
                            query_filter=query_filter,
                            limit=limit,
                            with_payload=with_payload,
                            with_vectors=with_vectors,
                        )
                        return list(getattr(result, "points", []) or [])
                    except Exception as fusion_error:
                        log.warning(
                            "[%s] RRF search failed; falling back to dense-only: %s",
                            log_label,
                            fusion_error,
                        )

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
        dense_vector_name: str,
        limit: int,
        title_vector_name: str | None,
        title_limit: int | None,
        sparse_vector: dict[str, list] | None,
        sparse_vector_name: str,
        sparse_limit: int | None,
    ) -> list[Any]:
        prefetches: list[Any] = [
            qmodels.Prefetch(
                query=query_vector,
                using=dense_vector_name,
                limit=limit,
            )
        ]
        if title_vector_name:
            prefetches.append(
                qmodels.Prefetch(
                    query=query_vector,
                    using=title_vector_name,
                    limit=title_limit or max(1, limit // 2),
                )
            )
        if sparse_vector is not None:
            prefetches.append(
                qmodels.Prefetch(
                    query=qmodels.SparseVector(
                        indices=sparse_vector["indices"],
                        values=sparse_vector["values"],
                    ),
                    using=sparse_vector_name,
                    limit=sparse_limit or limit,
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
        content_field: str = "content",
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
        document_id_field: str = "document_id",
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
        document_id_field: str = "document_id",
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
        document_id_field: str = "document_id",
        is_deleted_field: str = "is_deleted",
        chunk_id_field: str = "chunk_id",
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
                key=chunk_id_field,
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
        document_id_field: str = "document_id",
        is_deleted_field: str = "is_deleted",
        chunk_kind_field: str = "chunk_kind",
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
        document_id_field: str = "document_id",
        is_deleted_field: str = "is_deleted",
        hierarchy_node_id_field: str = "hierarchy_node_id",
        ancestor_ids_field: str = "ancestor_hierarchy_node_ids",
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
        document_id_field: str = "document_id",
        source_type_field: str = "source_type",
        space_key_field: str = "space_key",
        ancestor_ids_field: str = "ancestor_hierarchy_node_ids",
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

        field_map = {
            "doc_id": document_id_field,
            "source_type": source_type_field,
        }
        conditions.extend(
            VectorStoreFilterBuilder.business_conditions(
                payload_filters,
                field_map=field_map,
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
    def build_access_filter(
        cls,
        *,
        tenant_id: str,
        reader_ids: list[str] | set[str] | None = None,
        space_keys: list[str] | set[str] | None = None,
        is_admin: bool = False,
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
        source_type_field: str = "source_type",
        space_key_field: str = "space_key",
        ancestor_ids_field: str = "ancestor_hierarchy_node_ids",
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
        is_admin: bool = False,
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
        document_id_field: str = "document_id",
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
        object_key_matches = [
            qmodels.FieldCondition(
                key=f'{ACL_FIELD}."{_qdrant_json_path_segment(rid)}"',
                match=qmodels.MatchValue(value=1),
            )
            for rid in ids
        ]
        return qmodels.Filter(
            should=[
                qmodels.FieldCondition(
                    key=ACL_FIELD,
                    match=qmodels.MatchAny(any=ids),
                ),
                *object_key_matches,
            ]
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
        source_type = getattr(params, "source_type", None)
        if source_type:
            conditions.append(
                qmodels.FieldCondition(
                    key=source_type_field,
                    match=qmodels.MatchValue(value=source_type),
                )
            )
        space_key = getattr(params, "space_key", None)
        if space_key:
            conditions.append(
                qmodels.FieldCondition(
                    key=space_key_field,
                    match=qmodels.MatchValue(value=space_key),
                )
            )
        ancestor_node_id = getattr(params, "ancestor_node_id", None)
        if ancestor_node_id is not None:
            conditions.append(
                qmodels.FieldCondition(
                    key=ancestor_ids_field,
                    match=qmodels.MatchValue(value=ancestor_node_id),
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
            qmodels.FieldCondition(
                key=tenant_id_field,
                match=qmodels.MatchValue(value=_NO_TENANT_ID),
            ),
            cls.no_access_condition(),
        ]

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
