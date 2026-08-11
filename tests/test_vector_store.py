from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any

import pytest
from qdrant_client import models as qmodels

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import bothesis.document_index.vector_store as vector_store_module
from bothesis.document_index.vector_store import (
    ACL_FIELD,
    NO_READER_IDS,
    VectorStore,
    VectorStoreFilterBuilder,
)


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


def test_store_can_be_configured_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, Any] = {}

    def make_client(**kwargs: Any) -> RecordingClient:
        captured_kwargs.update(kwargs)
        return RecordingClient()

    monkeypatch.setenv("QDRANT_URL", "http://qdrant.internal:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "test-key")
    monkeypatch.setenv("QDRANT_COLLECTION", "tenant_chunks")
    monkeypatch.setenv("QDRANT_PREFER_GRPC", "true")
    monkeypatch.setattr(vector_store_module, "AsyncQdrantClient", make_client)

    store = VectorStore.from_environment(timeout=15)

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
    tenant_condition = next(
        condition
        for condition in query_filter.must
        if isinstance(condition, qmodels.FieldCondition) and condition.key == "tenant_id"
    )
    assert tenant_condition.match == qmodels.MatchValue(value="__no_tenant_id__")


def test_filters_are_deterministic_and_keep_zero_ancestor_ids() -> None:
    payload_filters = SimpleNamespace(source_system=["jira"], doc_id=["doc-1"])
    access_context = SimpleNamespace(
        tenant_id="tenant-1",
        reader_ids=["reader-2", "reader-1"],
        space_keys=[],
        is_admin=False,
    )
    search_params = SimpleNamespace(ancestor_node_id=0)

    query_filter = VectorStore.build_retrieval_filter(
        search_params,
        access_context=access_context,
        payload_filters=payload_filters,
    )

    assert query_filter.must is not None
    assert [
        condition.key
        for condition in query_filter.must
        if isinstance(condition, qmodels.FieldCondition)
    ] == [
        "is_deleted",
        "tenant_id",
        "source_system",
        "document_id",
        "ancestor_hierarchy_node_ids",
    ]
    acl_filter = next(
        condition for condition in query_filter.must if isinstance(condition, qmodels.Filter)
    )
    assert acl_filter.should is not None
    acl_list_condition = acl_filter.should[0]
    assert isinstance(acl_list_condition, qmodels.FieldCondition)
    assert acl_list_condition.match == qmodels.MatchAny(any=["reader-1", "reader-2"])


@pytest.mark.asyncio
async def test_acl_sync_removes_reserved_reader_id() -> None:
    client = RecordingClient()
    store = VectorStore(client=client, collection_name="chunks")

    await store.sync_document_acl(
        "doc-1",
        {"reader-2": 1, NO_READER_IDS: 1, "reader-1": 1},
    )

    assert client.set_payload_calls[0]["payload"] == {
        ACL_FIELD: ["reader-1", "reader-2"]
    }


@pytest.mark.asyncio
async def test_sparse_search_uses_fusion_without_a_title_vector() -> None:
    client = RecordingClient()
    store = VectorStore(client=client, collection_name="chunks")

    results = await store.semantic_search(
        [0.1, 0.2],
        query_filter=None,
        limit=3,
        title_vector_name=None,
        sparse_vector={"indices": [1, 3], "values": [0.4, 0.8]},
    )

    assert results == ["point-1"]
    request = client.query_points_calls[0]
    assert len(request["prefetch"]) == 2
    assert request["query"] == qmodels.FusionQuery(fusion=qmodels.Fusion.RRF)


def test_request_filter_fails_closed_when_the_request_lacks_access() -> None:
    query_filter = VectorStoreFilterBuilder.build_request_filter(SimpleNamespace())

    assert query_filter.must is not None
    assert any(
        isinstance(condition, qmodels.FieldCondition)
        and condition.key == "tenant_id"
        and condition.match == qmodels.MatchValue(value="__no_tenant_id__")
        for condition in query_filter.must
    )
