from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import api.app as api_app
import api.deps as api_deps
from bothesis.services import AuthContext
from bothesis.services.document_presentation import public_document_status
from bothesis.services.knowledge_view import _document_payload


def _caller() -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        email="reader@example.test",
        display_name="Reader",
        tenant_id=uuid4(),
        permission_codes=("knowledge.read",),
        group_ids=(),
        role_codes=("reader",),
    )


def _collection(collection_id: UUID) -> dict[str, object]:
    return {
        "id": str(collection_id),
        "title": "Travel & Expense",
        "description": "Policies and receipts.",
        "parent_collection_id": None,
        "status": "active",
        "document_count": 3,
        "source_count": 1,
        "created_at": "2026-09-12T09:00:00+00:00",
        "updated_at": "2026-09-12T10:00:00+00:00",
    }


def _document(document_id: UUID, collection_id: UUID) -> dict[str, object]:
    return {
        "id": str(document_id),
        "collection_id": str(collection_id),
        "name": "Travel reimbursement policy.pdf",
        "content_type": "application/pdf",
        "size_bytes": 100,
        "purpose": "knowledge",
        "status": "available",
        "latest_ingestion_id": None,
        "created_at": "2026-09-12T09:00:00+00:00",
        "updated_at": "2026-09-12T10:00:00+00:00",
    }


def test_knowledge_and_collection_routes_follow_resource_contract(monkeypatch) -> None:
    collection_id = uuid4()
    document_id = uuid4()
    calls: list[str] = []

    class Knowledge:
        async def get_workspace_home(self, caller: AuthContext) -> dict[str, object]:
            calls.append("home")
            return {
                "items": [_collection(collection_id)],
                "recent_documents": [_document(document_id, collection_id)],
                "personal_collection_id": None,
            }

    class ControlPlane:
        async def list_collections(self, caller: AuthContext, **_: object) -> dict[str, object]:
            calls.append("list")
            return {"items": [_collection(collection_id)], "page": 1, "page_size": 20, "total": 1}

        async def create_collection_contract(self, caller: AuthContext, values: dict[str, object]) -> dict[str, object]:
            calls.append("create")
            return _collection(collection_id)

        async def get_collection(self, caller: AuthContext, requested_id: UUID) -> dict[str, object]:
            calls.append("get")
            return _collection(requested_id)

    async def caller() -> AuthContext:
        return _caller()

    async def get_knowledge() -> Knowledge:
        return Knowledge()

    async def get_control_plane() -> ControlPlane:
        return ControlPlane()

    monkeypatch.setitem(api_app.app.dependency_overrides, api_deps.get_auth_context, caller)
    monkeypatch.setitem(api_app.app.dependency_overrides, api_deps.get_knowledge_view_service, get_knowledge)
    monkeypatch.setitem(api_app.app.dependency_overrides, api_deps.get_workspace_control_plane_service, get_control_plane)

    with TestClient(api_app.app) as client:
        home = client.get("/api/v1/knowledge/home")
        collections = client.get("/api/v1/collections")
        created = client.post("/api/v1/collections", json={"title": "Travel & Expense"})
        collection = client.get(f"/api/v1/collections/{collection_id}")

    assert home.status_code == 200, home.text
    assert home.json()["recent_documents"][0]["id"] == str(document_id)
    assert home.json()["recent_documents"][0]["status"] == "available"
    assert collections.status_code == 200, collections.text
    assert created.status_code == 201, created.text
    assert collection.status_code == 200, collection.text
    assert calls == ["home", "list", "create", "get"]


def test_knowledge_projection_maps_internal_ready_status_to_public_available() -> None:
    now = datetime.now(timezone.utc)
    item = SimpleNamespace(
        id=uuid4(),
        parent_item_id=uuid4(),
        title="Policy.pdf",
        mime_type="application/pdf",
        size_bytes=100,
        metadata_={"purpose": "knowledge"},
        status="ready",
        created_at=now,
        updated_at=now,
        document_type="pdf",
        external_resources=[],
    )

    payload = _document_payload(item)

    assert payload["status"] == "available"


def test_public_document_status_collapses_internal_lifecycle_values() -> None:
    assert public_document_status("pending") == "pending_content"
    assert public_document_status("processing") == "available"
    assert public_document_status("ready") == "available"
    assert public_document_status("unsupported") == "failed"
