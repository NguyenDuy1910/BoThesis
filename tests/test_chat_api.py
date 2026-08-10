from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import main
from bothesis.agent.models import TextDelta, TurnDone
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
from bothesis.agent.transports.base import ChatMessage, LLMResponse, LLMTransport
from bothesis.chat.agent_loop import AgentLoop
from bothesis.knowledge.document_index import RetrievedDocument


class ScriptedTransport(LLMTransport):
    def __init__(self) -> None:
        self.complete_requests: list[list[dict[str, Any]]] = []
        self.stream_requests: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> LLMResponse:
        self.complete_requests.append([dict(message) for message in messages])
        return LLMResponse(
            id="compression-1",
            model="openai/gpt-5.4-mini",
            content=(
                '{"summary":"Earlier question and answer about the leave policy."}'
            ),
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 3},
        )

    async def stream_turn(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[TextDelta | TurnDone]:
        self.stream_requests.append([dict(message) for message in messages])
        if len(self.stream_requests) == 1:
            yield TurnDone(
                "tool_calls",
                tool_calls=[
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "knowledge_search",
                            "arguments": '{"query":"leave policy"}',
                        },
                    }
                ],
            )
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
    loop = AgentLoop(transport, registry)
    monkeypatch.setattr(main, "_agent_loop", loop)
    long_assistant_answer = f"Earlier answer\n{'A' * 5_000}"

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
                    {"role": "assistant", "content": long_assistant_answer},
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
        "generation_started",
        "generation_completed",
        "tool_started",
        "citation_available",
        "tool_completed",
        "turn_completed",
        "turn_started",
        "generation_started",
        "message_delta",
        "citation",
        "message_delta",
        "generation_completed",
        "turn_completed",
        "run_completed",
    ]
    generation_events = [
        event for event in events if event["type"] == "generation_completed"
    ]
    assert generation_events[0]["generation_kind"] == "next_step"
    assert generation_events[0]["selected_tools"] == ["knowledge_search"]
    assert generation_events[1]["generation_kind"] == "final_response"
    citation_event = next(
        event for event in events if event["type"] == "citation_available"
    )
    assert citation_event["evidence"]["source"] == "confluence"
    assert "content" not in citation_event["evidence"]
    tool_event = next(event for event in events if event["type"] == "tool_completed")
    assert tool_event["result_count"] == 1
    assert events[-1]["tool_call_count"] == 1
    compression_prompt = transport.complete_requests[0][1]["content"]
    model_request = transport.stream_requests[0]
    assert "Compress the earlier conversation" in compression_prompt
    assert "Earlier answer" in compression_prompt
    assert (
        "Earlier question and answer about the leave policy"
        in model_request[1]["content"]
    )
    assert model_request[-1] == {
        "role": "user",
        "content": "What is the leave policy?",
    }


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
                    {"role": "user", "content": "previous turn"} for _ in range(9)
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
