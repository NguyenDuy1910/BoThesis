from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any

import pytest
from qdrant_client import models as qmodels

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import bothesis.document_index.vector_store as vector_store_module
from bothesis.document_index import INDEX_SCHEMA_VERSION
from bothesis.document_index.vector_store import VectorStore, VectorStoreFilterBuilder


class RecordingClient:
    def __init__(self) -> None:
        self.set_payload_calls: list[dict[str, Any]] = []
        self.query_points_calls: list[dict[str, Any]] = []

    async def set_payload(self, **kwargs: Any) -> dict[str, Any]:
        self.set_payload_calls.append(kwargs)
        return kwargs

    async def query_points(self, **kwargs: Any) -> SimpleNamespace:
        self.query_points_calls.append(kwargs)
        return SimpleNamespace(points=["point-1"])


def test_store_can_be_configured_through_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, Any] = {}

    def make_client(**kwargs: Any) -> RecordingClient:
        captured_kwargs.update(kwargs)
        return RecordingClient()

    monkeypatch.setattr(vector_store_module, "AsyncQdrantClient", make_client)
    store = VectorStore(
        collection_name="tenant_chunks",
        url="http://qdrant.internal:6333",
        api_key="test-key",
        prefer_grpc=True,
        timeout=15,
    )

    assert store.collection_name == "tenant_chunks"
    assert isinstance(store.client, RecordingClient)
    assert captured_kwargs == {
        "url": "http://qdrant.internal:6333",
        "port": None,
        "api_key": "test-key",
        "prefer_grpc": True,
        "timeout": 15,
        "check_compatibility": False,
    }


def test_missing_access_context_is_denied_for_a_nonexistent_tenant() -> None:
    query_filter = VectorStore.build_retrieval_filter(None)
    assert query_filter.must is not None
    assert any(
        isinstance(condition, qmodels.FieldCondition)
        and condition.key == "tenant_id"
        and condition.match == qmodels.MatchValue(value="__no_tenant_id__")
        for condition in query_filter.must
    )


def test_collection_authorization_and_business_filters_are_deterministic() -> None:
    query_filter = VectorStore.build_retrieval_filter(
        SimpleNamespace(ancestor_id="0"),
        access_context=SimpleNamespace(
            tenant_id="tenant-1",
            collection_item_ids=("collection-2", "collection-1", "collection-2"),
        ),
        payload_filters=SimpleNamespace(connector_key=["jira"], item_id=["doc-1"]),
    )

    assert [
        condition.key
        for condition in query_filter.must or []
        if isinstance(condition, qmodels.FieldCondition)
    ] == [
        "is_deleted",
        "schema_version",
        "tenant_id",
        "collection_item_id",
        "connector_key",
        "item_id",
        "ancestor_ids",
    ]
    collection_condition = (query_filter.must or [])[3]
    assert isinstance(collection_condition, qmodels.FieldCondition)
    assert collection_condition.match == qmodels.MatchAny(
        any=["collection-1", "collection-2"]
    )


def test_empty_collection_scope_fails_closed_inside_the_tenant() -> None:
    query_filter = VectorStore.build_retrieval_filter(
        None,
        access_context=SimpleNamespace(
            tenant_id="tenant-1", collection_item_ids=()
        ),
    )
    condition = next(
        value
        for value in query_filter.must or []
        if isinstance(value, qmodels.FieldCondition)
        and value.key == "collection_item_id"
    )
    assert condition.match == qmodels.MatchAny(any=["__no_collection_id__"])


def test_lifecycle_filter_excludes_tombstones_and_old_schema_versions() -> None:
    query_filter = VectorStore.build_lifecycle_filter()
    assert query_filter.must == [
        qmodels.FieldCondition(
            key="is_deleted", match=qmodels.MatchValue(value=False)
        ),
        qmodels.FieldCondition(
            key="schema_version",
            match=qmodels.MatchValue(value=INDEX_SCHEMA_VERSION),
        ),
    ]


@pytest.mark.asyncio
async def test_soft_delete_only_updates_derived_lifecycle_state() -> None:
    client = RecordingClient()
    store = VectorStore(client=client, collection_name="chunks")

    await store.soft_delete_document_points("doc-1")

    assert client.set_payload_calls[0]["payload"] == {"is_deleted": True}
    assert client.set_payload_calls[0]["points"] == VectorStore.document_filter("doc-1")


@pytest.mark.asyncio
async def test_contextual_hybrid_search_uses_filtered_bm25_and_rrf() -> None:
    client = RecordingClient()
    store = VectorStore(client=client, collection_name="chunks")
    query_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="tenant_id", match=qmodels.MatchValue(value="tenant-1")
            )
        ]
    )

    results = await store.semantic_search(
        [0.1, 0.2],
        query_text="doanh thu quý II",
        query_filter=query_filter,
        limit=3,
    )

    assert results == ["point-1"]
    request = client.query_points_calls[0]
    assert len(request["prefetch"]) == 2
    assert request["query"] == qmodels.FusionQuery(fusion=qmodels.Fusion.RRF)
    dense, sparse = request["prefetch"]
    assert dense.filter is query_filter
    assert sparse.filter is query_filter
    assert request["query_filter"] is query_filter


def test_request_filter_fails_closed_when_the_request_lacks_access() -> None:
    query_filter = VectorStoreFilterBuilder.build_request_filter(SimpleNamespace())
    assert any(
        isinstance(condition, qmodels.FieldCondition)
        and condition.key == "tenant_id"
        and condition.match == qmodels.MatchValue(value="__no_tenant_id__")
        for condition in query_filter.must or []
    )
