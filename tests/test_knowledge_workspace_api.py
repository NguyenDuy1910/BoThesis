from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import api.app as api_app
import api.deps as api_deps
from bothesis.services import AuthContext


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


def _collection_payload(collection_id: UUID) -> dict[str, object]:
    return {
        "id": str(collection_id),
        "title": "Travel & Expense",
        "description": "Policies and receipts.",
        "parent_item_id": None,
        "document_count": 3,
        "source_count": 1,
        "updated_at": "2026-09-12T10:00:00+00:00",
    }


def _document_payload(document_id: UUID) -> dict[str, object]:
    return {
        "id": str(document_id),
        "title": "Travel reimbursement policy.pdf",
        "content_type": "application/pdf",
        "document_type": "pdf",
        "status": "ready",
        "updated_at": "2026-09-12T10:00:00+00:00",
        "source": {
            "display_name": "Confluence",
            "connector_key": "confluence",
            "source_url": "https://knowledge.example.test/travel",
        },
    }


def test_knowledge_collection_routes_use_the_workspace_view_contract(
    monkeypatch,
) -> None:
    collection_id = uuid4()
    document_id = uuid4()
    calls: list[tuple[str, object]] = []

    class WorkspaceView:
        async def get_workspace_home(self, caller: AuthContext) -> dict[str, object]:
            calls.append(("home", caller.user_id))
            return {
                "items": [_collection_payload(collection_id)],
                "total": 1,
                "recent_documents": [_document_payload(document_id)],
                "personal_collection_id": None,
            }

        async def get_collection_workspace(
            self,
            caller: AuthContext,
            *,
            collection_id: UUID,
            search: str | None,
            page: int,
            page_size: int,
        ) -> dict[str, object]:
            calls.append(("collection", (collection_id, search, page, page_size)))
            return {
                "collection": _collection_payload(collection_id),
                "child_collections": [],
                "documents": [_document_payload(document_id)],
                "total": 1,
                "page": page,
                "page_size": page_size,
            }

    class WorkspaceAdmin:
        async def create_collection(
            self, caller: AuthContext, values: dict[str, object]
        ) -> dict[str, object]:
            calls.append(("create", values))
            return {"id": collection_id, "title": values["title"]}

    async def caller() -> AuthContext:
        return _caller()

    monkeypatch.setitem(api_app.app.dependency_overrides, api_deps.get_auth_context, caller)
    monkeypatch.setitem(
        api_app.app.dependency_overrides,
        api_deps.get_knowledge_view_service,
        WorkspaceView,
    )
    monkeypatch.setitem(
        api_app.app.dependency_overrides,
        api_deps.get_admin_console_service,
        WorkspaceAdmin,
    )

    with TestClient(api_app.app) as client:
        created = client.post(
            "/api/v1/knowledge/collections",
            json={"title": "Travel & Expense", "description": "Policies and receipts."},
        )
        home = client.get("/api/v1/knowledge/collections")
        collection = client.get(
            f"/api/v1/knowledge/collections/{collection_id}",
            params={"search": "travel", "page": 2, "page_size": 25},
        )

    assert created.status_code == 201, created.text
    assert created.json() == {"id": str(collection_id), "title": "Travel & Expense"}
    assert calls[0] == (
        "create",
        {
            "title": "Travel & Expense",
            "inherit_access": True,
            "metadata": {"description": "Policies and receipts."},
        },
    )
    assert home.status_code == 200, home.text
    assert home.json()["recent_documents"][0]["source"]["connector_key"] == "confluence"
    assert collection.status_code == 200, collection.text
    assert collection.json()["collection"]["id"] == str(collection_id)
    assert calls[1][0] == "home"
    assert calls[2] == ("collection", (collection_id, "travel", 2, 25))
