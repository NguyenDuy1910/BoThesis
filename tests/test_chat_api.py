from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import main
from bothesis.agent.models import TextDelta, ToolCallDelta, TurnDone
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
from bothesis.agent.transports.base import ChatMessage, LLMResponse, LLMTransport
from bothesis.chat.agent_loop import AgentLoop
from bothesis.knowledge.document_index import RetrievedDocument


class ScriptedTransport(LLMTransport):
    def __init__(self) -> None:
        self.requests: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> LLMResponse:
        raise AssertionError("the API integration path must stream")

    async def stream_turn(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[TextDelta | ToolCallDelta | TurnDone]:
        self.requests.append([dict(message) for message in messages])
        if len(self.requests) == 1:
            yield ToolCallDelta("call-1", "knowledge_search", '{"query":"leave policy"}')
            yield TurnDone("tool_calls")
            return
        yield TextDelta("Employees receive 20 days of annual leave [[cite:chunk-1]].")
        yield TurnDone("stop")


class StubRetriever:
    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        assert query == "leave policy"
        assert limit == 5
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


def test_chat_api_streams_agent_retrieval_and_sources(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(KnowledgeSearchTool(StubRetriever()))
    transport = ScriptedTransport()
    loop = AgentLoop(transport, registry, "Use enterprise evidence.")
    monkeypatch.setattr(main, "_agent_loop", loop)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "What is the leave policy?",
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "roles": [],
                "conversation_id": "conversation-1",
                "history": [
                    {"role": "user", "content": "Earlier question"},
                    {"role": "assistant", "content": "Earlier answer"},
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
        "run_started",
        "turn_started",
        "tool_started",
        "citation_available",
        "tool_completed",
        "turn_completed",
        "turn_started",
        "message_delta",
        "citation",
        "message_delta",
        "turn_completed",
        "run_completed",
    ]
    assert events[3]["evidence"]["source"] == "confluence"
    assert "content" not in events[3]["evidence"]
    assert events[4]["result_count"] == 1
    assert events[-1]["tool_call_count"] == 1
    assert transport.requests[0][1:4] == [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
        {"role": "user", "content": "What is the leave policy?"},
    ]


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
                    {"role": "user", "content": "previous turn"}
                    for _ in range(9)
                ],
            },
        )

    assert response.status_code == 422
