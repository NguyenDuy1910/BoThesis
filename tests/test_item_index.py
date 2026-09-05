from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from qdrant_client import models as qmodels

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import bothesis.document_index._qdrant as qdrant_module
from bothesis.document_index import INDEX_SCHEMA_VERSION, ItemIndex
from bothesis.document_index._qdrant import _QdrantBackend


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


def test_private_qdrant_transport_uses_explicit_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def make_client(**kwargs: Any) -> RecordingClient:
        captured.update(kwargs)
        return RecordingClient()

    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", make_client)
    backend = _QdrantBackend(
        collection_name="tenant_chunks",
        url="http://qdrant.internal:6333",
        api_key="test-key",
        prefer_grpc=True,
        timeout=15,
    )

    assert backend.collection_name == "tenant_chunks"
    assert isinstance(backend.client, RecordingClient)
    assert captured == {
        "url": "http://qdrant.internal:6333",
        "port": None,
        "api_key": "test-key",
        "prefer_grpc": True,
        "timeout": 15,
        "check_compatibility": False,
    }


def test_access_filter_is_tenant_collection_lifecycle_and_schema_scoped() -> None:
    query_filter = _QdrantBackend._access_filter(
        tenant_id="tenant-1",
        collection_item_ids=("collection-2", "collection-1", "collection-2"),
    )

    assert query_filter.must == [
        qmodels.FieldCondition(key="is_deleted", match=qmodels.MatchValue(value=False)),
        qmodels.FieldCondition(
            key="schema_version",
            match=qmodels.MatchValue(value=INDEX_SCHEMA_VERSION),
        ),
        qmodels.FieldCondition(
            key="tenant_id", match=qmodels.MatchValue(value="tenant-1")
        ),
        qmodels.FieldCondition(
            key="collection_item_id",
            match=qmodels.MatchAny(any=["collection-1", "collection-2"]),
        ),
    ]


def test_empty_collection_scope_fails_closed_inside_the_tenant() -> None:
    query_filter = _QdrantBackend._access_filter(
        tenant_id="tenant-1", collection_item_ids=()
    )
    condition = (query_filter.must or [])[3]
    assert isinstance(condition, qmodels.FieldCondition)
    assert condition.match == qmodels.MatchAny(any=["__no_collection_id__"])


@pytest.mark.asyncio
async def test_item_removal_only_tombstones_derived_content() -> None:
    client = RecordingClient()
    index = ItemIndex(backend=_QdrantBackend(client=client, collection_name="chunks"))

    await index.remove_item_content("doc-1", tenant_id="tenant-1")

    assert client.set_payload_calls[0]["payload"] == {"is_deleted": True}
    assert client.set_payload_calls[0]["points"] == qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="tenant_id",
                match=qmodels.MatchValue(value="tenant-1"),
            ),
            qmodels.FieldCondition(
                key="item_id", match=qmodels.MatchValue(value="doc-1")
            ),
        ]
    )


@pytest.mark.asyncio
async def test_hybrid_search_uses_scoped_dense_bm25_and_rrf() -> None:
    client = RecordingClient()
    backend = _QdrantBackend(client=client, collection_name="chunks")

    results = await backend.search_item_points(
        query_vector=[0.1, 0.2],
        query_text="doanh thu quý II",
        tenant_id="tenant-1",
        collection_item_ids=("collection-1",),
        limit=3,
        candidate_limit=20,
    )

    assert results == ["point-1"]
    request = client.query_points_calls[0]
    assert len(request["prefetch"]) == 2
    assert request["query"] == qmodels.FusionQuery(fusion=qmodels.Fusion.RRF)
    dense, sparse = request["prefetch"]
    assert dense.filter is request["query_filter"]
    assert sparse.filter is request["query_filter"]
