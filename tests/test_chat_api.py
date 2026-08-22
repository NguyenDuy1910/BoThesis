from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
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
import bothesis.db.engine as db_engine
from bothesis.agent import Agent, AgentConfig
from bothesis.agent.models import AgentContext
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
from bothesis.knowledge.document_index import RetrievedDocument
from bothesis.services import AuthContext


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

    monkeypatch.setattr(
        openrouter_transport,
        "OpenRouterTransport",
        TestOpenRouterTransport,
    )
    monkeypatch.setattr(main, "_agent", None)

    assert isinstance(main._get_agent().model, TestOpenRouterTransport)


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

    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        assert query == "leave policy"
        assert limit == 5
        return self._documents()

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: Any,
    ) -> list[RetrievedDocument]:
        assert query == "leave policy"
        assert limit == 5
        self.contexts.append(ctx)
        return self._documents()

    @staticmethod
    def _documents() -> list[RetrievedDocument]:
        return [
            RetrievedDocument(
                id="chunk-1",
                document_id="doc-1",
                title="Leave policy",
                content="Employees receive 20 days of annual leave.",
                source="confluence",
                uri="https://knowledge.example/leave-policy",
                metadata={"section_title": "Annual leave"},
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
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
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
            principal_tokens=("external_group:finance",),
        )

    monkeypatch.setattr(main, "_resolve_access", resolve_access)
    monkeypatch.setattr(db_engine, "get_session_factory", lambda: _SessionContext)
    return user_id, tenant_id


def test_chat_api_streams_agent_retrieval_and_sources(monkeypatch) -> None:
    registry = ToolRegistry()
    retriever = StubRetriever()
    registry.register(KnowledgeSearchTool(retriever))
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
    monkeypatch.setattr(main, "_agent", agent)
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
    assert annotation["citation"]["document_id"] == "doc-1"
    assert annotation["citation"]["source"] == "confluence"
    assert len(retriever.contexts) == 1
    assert retriever.contexts[0].reader_ids == (
        "email:person@example.test",
        "external_group:finance",
    )
    assert retriever.contexts[0].is_admin is True
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
    registry.register(KnowledgeSearchTool(StubRetriever()))
    agent = Agent(InterleavedTransport(), registry)
    monkeypatch.setattr(main, "_agent", agent)
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
    registry.register(KnowledgeSearchTool(StubRetriever()))
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
