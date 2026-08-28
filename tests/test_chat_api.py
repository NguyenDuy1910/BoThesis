from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from openai import PermissionDeniedError
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import native_responses as native

import main
import bothesis.services.api as api_service_module
from bothesis.agent import Agent, AgentConfig
from bothesis.agent.models import AgentContext
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearch
from bothesis.connector.protocol import (
    CitationInfo,
    CitationSpan,
    SourceIdentity,
    SourceProvider,
)
from bothesis.knowledge import Evidence
from bothesis.document_index import DocumentProcessingError
from bothesis.services import AuthContext, RequestIdentity


def search_call(output_index: int = 0) -> list[Any]:
    return native.function_call(
        item_id="fc_1",
        output_index=output_index,
        call_id="search-1",
        name="knowledge_search",
        argument_deltas=['{"queries":["leave policy"]}'],
    )


class ScriptedTransport(native.ScriptedResponsesTransport):
    """Retrieve once, then answer with a citation marker."""

    def __init__(self) -> None:
        super().__init__(
            [
                [*native.created("resp_a"), *search_call(), *native.completed("resp_a")],
                [
                    *native.created("resp_b"),
                    *native.message(
                        item_id="msg_1",
                        output_index=0,
                        deltas=[
                            "Employees receive 20 days of annual leave "
                            "[[cite:chunk-1]]."
                        ],
                        phase="final_answer",
                    ),
                    *native.completed("resp_b"),
                ],
            ]
        )

    @property
    def stream_requests(self) -> list[list[dict[str, Any]]]:
        """The canonical input items of each sampling request."""

        return [request["input"] for request in self.requests]


def test_default_agent_composes_the_openrouter_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bothesis.agent.transports import openrouter as openrouter_transport

    class TestOpenRouterTransport:
        DEFAULT_BASE_URL = "https://openrouter.test/v1"
        provider = "openrouter"
        model = "gpt-test"

        def __init__(self, **_: Any) -> None:
            pass

        async def stream_response(
            self,
            *_: Any,
            **__: Any,
        ) -> AsyncIterator[Any]:
            if False:
                yield None

    monkeypatch.setattr(openrouter_transport, "OpenRouterTransport", TestOpenRouterTransport)
    monkeypatch.setattr(api_service_module, "OpenRouterTransport", TestOpenRouterTransport)
    monkeypatch.setattr(main._api_service, "_agent", None)

    assert isinstance(main._api_service._get_agent().model, TestOpenRouterTransport)


class PermissionDeniedTransport:
    provider = "openai"
    model = "gpt-test"

    async def stream_response(self, **_: Any) -> Any:
        request = httpx.Request("POST", "https://api.openai.test/v1/responses")
        response = httpx.Response(403, request=request)
        raise PermissionDeniedError(
            "Your request was blocked.",
            response=response,
            body=None,
        )


@pytest.mark.asyncio
async def test_agent_returns_a_safe_model_access_error_for_openai_denials() -> None:
    events = [
        event
        async for event in Agent(PermissionDeniedTransport(), ToolRegistry()).run(  # type: ignore[arg-type]
            "Hello",
            AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[]),
        )
    ]

    assert [event.type for event in events] == ["response.failed"]
    assert events[0].response.error is not None
    assert events[0].response.error.code == "model_access_denied"
    assert "configured model" in events[0].response.error.message


class StubRetriever:
    def __init__(self) -> None:
        self.contexts: list[Any] = []

    async def search(
        self,
        query: str,
        *,
        limit: int,
        ctx: Any,
    ) -> list[Evidence]:
        assert query == "leave policy"
        assert limit == 5
        self.contexts.append(ctx)
        return self._evidence()

    @staticmethod
    def _evidence() -> list[Evidence]:
        return [
            Evidence(
                id="chunk-1",
                item_id="doc-1",
                chunk_id="chunk-1",
                title="Leave policy",
                content="Employees receive 20 days of annual leave.",
                source=SourceIdentity(
                    connector_id="connector-1",
                    provider=SourceProvider.CONFLUENCE,
                    external_id="doc-1",
                    url="https://knowledge.example/leave-policy",
                ),
                citation=CitationInfo(
                    section="Annual leave",
                    section_path=("Annual leave",),
                    spans=(CitationSpan(
                        element_id="paragraph_001",
                        start_offset=0,
                        end_offset=len("Employees receive 20 days of annual leave."),
                    ),),
                ),
                relevance_score=0.9,
            )
        ]


class InterleavedTransport(native.ScriptedResponsesTransport):
    """Emit user-visible commentary before retrieving, then answer."""

    def __init__(self) -> None:
        super().__init__(
            [
                [
                    *native.created("resp_a"),
                    *native.message(
                        item_id="msg_1",
                        output_index=0,
                        deltas=["I’ll check the relevant source first."],
                        phase="commentary",
                    ),
                    *search_call(output_index=1),
                    *native.completed("resp_a"),
                ],
                [
                    *native.created("resp_b"),
                    *native.message(
                        item_id="msg_2",
                        output_index=0,
                        deltas=["Employees receive 20 days ", "[[cite:chunk-1]]."],
                        phase="final_answer",
                    ),
                    *native.completed("resp_b"),
                ],
            ]
        )


class ReasoningTransport(native.ScriptedResponsesTransport):
    """Emit a reasoning item, retrieve, then answer."""

    def __init__(self) -> None:
        super().__init__(
            [
                [
                    *native.created("resp_a"),
                    *native.reasoning(
                        item_id="rs_1",
                        output_index=0,
                        summary="I should search the policy.",
                        text="private raw reasoning",
                        encrypted_content="opaque",
                    ),
                    *search_call(output_index=1),
                    *native.completed("resp_a"),
                ],
                [
                    *native.created("resp_b"),
                    *native.message(
                        item_id="msg_1",
                        output_index=0,
                        deltas=["Employees receive 20 days."],
                        phase="final_answer",
                    ),
                    *native.completed("resp_b"),
                ],
            ]
        )


class _SessionContext:
    async def __aenter__(self) -> _SessionContext:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _install_access(monkeypatch: Any) -> tuple[UUID, UUID]:
    user_id = uuid4()
    tenant_id = uuid4()

    async def resolve_access(*args: Any, **kwargs: Any) -> AuthContext:
        return AuthContext(
            user_id=user_id,
            email="person@example.test",
            display_name="Person",
            tenant_id=tenant_id,
            role_id=uuid4(),
            role_code="analyst",
            permission_codes=("admin", "knowledge.read"),
            group_ids=(),
        )

    monkeypatch.setattr(main._api_service, "_resolve_access", resolve_access)
    monkeypatch.setattr(main._api_service, "_session_factory", _SessionContext)
    async def allowed_collections(*_: Any, **__: Any) -> tuple[UUID, ...]:
        return (UUID(int=12), UUID(int=14))

    monkeypatch.setattr(
        "bothesis.services.api.CollectionAccessService.allowed_collection_ids",
        allowed_collections,
    )
    return user_id, tenant_id


def test_collection_upload_route_accepts_multipart_without_a_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    now = datetime.now(UTC).isoformat()

    async def upload_collection_document(
        identity: RequestIdentity,
        requested_collection_id: UUID,
        **values: Any,
    ) -> dict[str, Any]:
        assert identity.tenant_id == str(tenant_id)
        assert identity.user_id == str(user_id)
        assert requested_collection_id == collection_id
        assert values["idempotency_key"] == "upload-contract-1"
        assert values["file_name"] == "policy.txt"
        assert values["content_type"] == "text/plain"
        assert await values["content"].read() == b"governed policy"
        return {
            "document": {
                "id": str(uuid4()),
                "parent_item_id": str(collection_id),
                "file_name": "policy.txt",
                "content_type": "text/plain",
                "size_bytes": 15,
                "status": "ready",
                "indexed": True,
                "upload_status": "available",
                "created_at": now,
                "uploaded_at": now,
            },
            "ingestion_status": "ready",
            "created": True,
        }

    monkeypatch.setattr(
        main._api_service,
        "upload_collection_document",
        upload_collection_document,
    )
    with TestClient(main.app) as client:
        response = client.post(
            f"/api/v1/collections/{collection_id}/documents/upload",
            headers={
                "Idempotency-Key": "upload-contract-1",
                "X-Bothesis-Tenant-Id": str(tenant_id),
                "X-Bothesis-User-Id": str(user_id),
            },
            files={"file": ("policy.txt", b"governed policy", "text/plain")},
        )

    assert response.status_code == 201
    assert response.json()["document"]["parent_item_id"] == str(collection_id)
    assert response.json()["ingestion_status"] == "ready"


@pytest.mark.asyncio
async def test_collection_upload_reports_ingestion_dispatch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = api_service_module.ApiService(
        allow_insecure_development_identity=True,
        qdrant_prefer_grpc=False,
    )
    user_id = uuid4()
    tenant_id = uuid4()
    collection_id = uuid4()
    now = datetime.now(UTC)
    upload_record = SimpleNamespace(status="available", uploaded_at=now)
    document = SimpleNamespace(
        id=uuid4(),
        parent_item_id=collection_id,
        title="policy.txt",
        mime_type="text/plain",
        size_bytes=15,
        status="ready",
        metadata_={"file_name": "policy.txt"},
        upload=upload_record,
        created_at=now,
    )
    access = AuthContext(
        user_id=user_id,
        email="editor@example.test",
        display_name="Editor",
        tenant_id=tenant_id,
        role_id=uuid4(),
        role_code="editor",
        permission_codes=(),
        group_ids=(),
    )

    class Uploads:
        async def upload_to_collection(self, *_: Any, **__: Any) -> Any:
            return SimpleNamespace(item=document, created=True)

        async def get_document(self, *_: Any, **__: Any) -> Any:
            return document

    class Pipeline:
        attempts = 0

        async def index_document(self, *_: Any, **__: Any) -> Any:
            self.attempts += 1
            if self.attempts == 1:
                document.status = "failed"
                raise DocumentProcessingError("index dispatch failed")
            document.status = "ready"
            document.metadata_["processing"] = {"index_schema_version": "test"}
            return document

    async def resolve_access(*_: Any, **__: Any) -> AuthContext:
        return access

    async def record_audit(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(service, "_resolve_access", resolve_access)
    monkeypatch.setattr(service, "_uploads", Uploads())
    monkeypatch.setattr(service, "_pipeline", Pipeline())
    monkeypatch.setattr(service, "_session_factory", _SessionContext)
    monkeypatch.setattr(api_service_module.AuditService, "record", record_audit)

    result = await service.upload_collection_document(
        RequestIdentity(user_id=user_id, tenant_id=tenant_id),
        collection_id,
        idempotency_key="dispatch-failure",
        file_name="policy.txt",
        content_type="text/plain",
        content=SimpleNamespace(read=lambda *_: b""),
    )

    assert result["created"] is True
    assert result["ingestion_status"] == "failed"
    assert result["document"]["status"] == "failed"
    assert result["document"]["parent_item_id"] == str(collection_id)

    retried = await service.retry_document_indexing(
        RequestIdentity(user_id=user_id, tenant_id=tenant_id),
        document.id,
    )

    assert retried["created"] is False
    assert retried["ingestion_status"] == "ready"
    assert retried["document"]["status"] == "ready"
    assert retried["document"]["indexed"] is True


def test_qdrant_citation_does_not_synthesize_element_ranges() -> None:
    payload = {
        "chunk_index": 4,
        "chunk_text": "Projected chunk evidence",
        "citation_section": "Canonical section",
        "citation_section_path": ["Policy", "Canonical section"],
        "citation_anchor": "canonical-section",
    }

    citation = main._api_service._payload_citation(payload)

    assert citation.spans == ()
    assert citation.section == "Canonical section"
    assert citation.section_path == ("Policy", "Canonical section")
    assert citation.anchor == "canonical-section"


def test_qdrant_viewer_does_not_split_multispan_chunk_projection() -> None:
    payload = {
        "chunk_id": "chunk-multi",
        "chunk_index": 0,
        "chunk_text": "First element\n\nSecond element",
        "citation_section_path": ["Policy"],
        "citation_spans": [
            {"page": 1, "element_id": "p001_para_001"},
            {"page": 2, "element_id": "p002_para_001"},
        ],
    }

    elements, chunks_by_id = main._api_service._viewer_elements(
        "doc-1", [payload]
    )

    assert elements == []
    assert chunks_by_id["chunk-multi"] is payload
    assert main._api_service._payload_citation(payload).spans == (
        CitationSpan(page=1, element_id="p001_para_001"),
        CitationSpan(page=2, element_id="p002_para_001"),
    )


def test_chat_api_streams_agent_retrieval_and_sources(monkeypatch) -> None:
    registry = ToolRegistry()
    retriever = StubRetriever()
    registry.register(KnowledgeSearch(retriever))
    transport = ScriptedTransport()
    agent = Agent(
        transport,
        registry,
        config=AgentConfig(
            max_model_turns=3,
            max_tool_rounds=2,
            recent_history_messages=2,
        ),
    )
    monkeypatch.setattr(main._api_service, "_agent", agent)
    user_id, tenant_id = _install_access(monkeypatch)
    conversation_id = uuid4()

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "What is the leave policy?",
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "roles": [],
                "conversation_id": str(conversation_id),
                "history": [
                    {"role": "user", "content": "Recent scope question"},
                    {"role": "assistant", "content": "Recent scope answer"},
                ],
                "knowledge_mode": "selected",
                "collection_item_ids": [str(UUID(int=12))],
            },
        )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    event_types = [event["type"] for event in events]
    assert event_types[0] == "response.created"
    assert event_types[-1] == "response.completed"
    assert [event["sequence_number"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert event_types.count("response.created") == 2
    assert event_types.count("response.completed") == 2
    function_call = next(
        event["item"]
        for event in events
        if event["type"] == "response.output_item.done"
        and event.get("item", {}).get("type") == "function_call"
    )
    assert function_call["call_id"] == "search-1"
    assert function_call["name"] == "knowledge_search"
    annotation = next(
        event["annotation"]
        for event in events
        if event["type"] == "response.output_text.annotation.added"
    )
    assert annotation["type"] == "bothesis:document_citation"
    assert annotation["citation"]["item_id"] == "doc-1"
    assert annotation["citation"]["chunk_id"] == "chunk-1"
    assert annotation["citation"]["source"]["provider"] == "confluence"
    assert len(retriever.contexts) == 1
    assert len(retriever.contexts[0].collection_item_ids) == 1
    # ``/responses`` takes instructions as a request parameter, so the input is
    # items only — there is no synthetic leading system message.
    assert "<agent_instructions>" in transport.requests[0]["instructions"]
    assert transport.stream_requests[0] == [
        {"type": "message", "role": "user", "content": "Recent scope question"},
        {"type": "message", "role": "assistant", "content": "Recent scope answer"},
        {
            "type": "message",
            "role": "user",
            "content": "<user_message>What is the leave policy?</user_message>",
        },
    ]


def test_chat_api_flushes_safe_interleaved_events(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(KnowledgeSearch(StubRetriever()))
    agent = Agent(InterleavedTransport(), registry)
    monkeypatch.setattr(main._api_service, "_agent", agent)
    user_id, tenant_id = _install_access(monkeypatch)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "What is the internal leave policy?",
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "roles": [],
                "history": [],
            },
        )

    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    event_types = [event["type"] for event in events]
    assert event_types[0] == "response.created"
    assert event_types[-1] == "response.completed"
    assert event_types.count("response.completed") == 2
    call = next(
        event["item"]
        for event in events
        if event["type"] == "response.output_item.done"
        and event.get("item", {}).get("type") == "function_call"
    )
    assert call["call_id"] == "search-1"
    message = next(
        event["item"]
        for event in events
        if event["type"] == "response.output_item.done"
        and event.get("item", {}).get("type") == "message"
        and event["item"]["content"][0]["text"] == "I’ll check the relevant source first."
    )
    assert message["status"] == "completed"


@pytest.mark.asyncio
async def test_a_reasoning_item_replays_as_a_canonical_input_item() -> None:
    """Reasoning continues through the specified fields, not a provider blob."""

    registry = ToolRegistry()
    registry.register(KnowledgeSearch(StubRetriever()))
    transport = ReasoningTransport()
    events = [
        event
        async for event in Agent(transport, registry).run(
            "What is the leave policy?",
            AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[]),
        )
    ]

    assert events[-1].type == "response.completed"
    replayed = transport.requests[1]["input"]
    reasoning = next(item for item in replayed if item.get("type") == "reasoning")
    assert reasoning == {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "I should search the policy."}],
        "id": "rs_1",
        "encrypted_content": "opaque",
    }
    # Raw reasoning text is never replayed: the specification's input item
    # carries the summary and the opaque continuation blob only.
    assert "private raw reasoning" not in json.dumps(replayed)


# Incremental delta forwarding, citation-boundary buffering and literal-bracket
# handling are covered by tests/bothesis/agent/test_conversation_loop.py, which
# exercises the same paths without going through the HTTP layer.


def test_chat_api_rejects_unbounded_history() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "hello",
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "roles": [],
                "history": [
                    {"role": "user", "content": "previous turn"} for _ in range(25)
                ],
            },
        )

    assert response.status_code == 422


def test_chat_api_rejects_history_message_over_context_budget() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "hello",
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "roles": [],
                "history": [{"role": "assistant", "content": "A" * 8_001}],
            },
        )

    assert response.status_code == 422


def test_chat_request_requires_a_bounded_explicit_collection_selection() -> None:
    with pytest.raises(ValueError, match="requires at least one Collection"):
        main.ChatRequest(message="hello", knowledge_mode="selected")

    request = main.ChatRequest(
        message="hello",
        knowledge_mode="selected",
        collection_item_ids=[UUID(int=12), UUID(int=14)],
    )

    assert request.collection_item_ids == [UUID(int=12), UUID(int=14)]
