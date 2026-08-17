from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import main
import bothesis.db.engine as db_engine
from bothesis.agent import Agent, AgentConfig
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
from bothesis.knowledge.document_index import RetrievedDocument
from bothesis.services import AuthContext


def text_delta(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}}]}


def turn_done(
    finish_reason: str,
    *,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if tool_calls:
        delta["tool_calls"] = [
            {"index": index, **call} for index, call in enumerate(tool_calls)
        ]
    return {"choices": [{"delta": delta, "finish_reason": finish_reason}]}


class ScriptedTransport:
    provider = "openrouter"
    model = "openai/gpt-5.4-mini"

    def __init__(self) -> None:
        self.stream_requests: list[list[dict[str, Any]]] = []

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.stream_requests.append([dict(message) for message in messages])
        if len(self.stream_requests) == 1:
            yield turn_done(
                "tool_calls",
                tool_calls=[
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "knowledge_search",
                            "arguments": '{"queries":["leave policy"]}',
                        },
                    }
                ],
            )
            return
        yield text_delta("Employees receive 20 days of annual leave [[cite:chunk-1]].")
        yield turn_done("stop")


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


class InterleavedTransport:
    provider = "openrouter"
    model = "openai/gpt-5.4-mini"

    def __init__(self) -> None:
        self.turn = 0

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.turn += 1
        if self.turn == 1:
            yield text_delta("I’ll check the relevant source first.")
            yield turn_done(
                "tool_calls",
                tool_calls=[
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "knowledge_search",
                            "arguments": '{"queries":["leave policy"]}',
                        },
                    }
                ],
            )
            return
        yield text_delta("Employees receive 20 days ")
        yield text_delta("[[cite:chunk-1]].")
        yield turn_done("stop")


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
    assert [event["type"] for event in events] == [
        "tool_started",
        "citation_available",
        "tool_completed",
        "final_answer_delta",
        "citation",
        "final_answer_delta",
        "run_completed",
    ]
    citation_event = next(
        event for event in events if event["type"] == "citation_available"
    )
    assert citation_event["evidence"]["source"] == "confluence"
    assert citation_event["evidence"]["snippet"] == (
        "Employees receive 20 days of annual leave."
    )
    assert "content" not in citation_event["evidence"]
    tool_event = next(event for event in events if event["type"] == "tool_completed")
    assert tool_event["result_count"] == 1
    started_tool_event = next(
        event for event in events if event["type"] == "tool_started"
    )
    assert started_tool_event["activity_id"] == tool_event["activity_id"]
    assert tool_event["label"] == "Search knowledge base"
    assert tool_event["category"] == "retrieval"
    assert tool_event["status"] == "completed"
    assert events[-1]["tool_call_count"] == 1
    assert len(retriever.contexts) == 1
    assert retriever.contexts[0].reader_ids == (
        "email:person@example.test",
        "external_group:finance",
    )
    assert retriever.contexts[0].is_admin is True
    model_request = transport.stream_requests[0]
    assert model_request[0]["role"] == "system"
    assert model_request[1:] == [
        {"role": "user", "content": "Recent scope question"},
        {"role": "assistant", "content": "Recent scope answer"},
        {"role": "user", "content": "What is the leave policy?"},
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
    assert [event["type"] for event in events] == [
        "commentary_delta",
        "tool_started",
        "citation_available",
        "tool_completed",
        "final_answer_delta",
        "citation",
        "final_answer_delta",
        "run_completed",
    ]
    tool_event = next(event for event in events if event["type"] == "tool_started")
    assert tool_event["call_id"] == "search-1"
    assert "arguments" not in tool_event
    assert tool_event["label"] == "Search knowledge base"
    assert tool_event["activity_id"]
    assert tool_event["category"] == "retrieval"
    citation = next(event for event in events if event["type"] == "citation_available")
    assert citation["evidence"]["document_id"] == "doc-1"
    assert citation["evidence"]["snippet"] == (
        "Employees receive 20 days of annual leave."
    )


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
