from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from bothesis.tui.client import (
    BothesisChatClient,
    ChatClientConfig,
    ChatRequestError,
)
from bothesis.tui.state import ChatState, HistoryMessage


@pytest.mark.asyncio
async def test_client_posts_current_chat_contract_and_preserves_sse_order() -> None:
    captured: dict[str, Any] = {}
    lines = [
        'data: {"type":"turn.started"}',
        ': ignored SSE comment',
        'data: {"type":"item.delta","item_id":"message-1","delta":"Hi"}',
        'data: {"type":"turn.completed"}',
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            content=("\n".join(lines) + "\n\n").encode(),
        )

    client = BothesisChatClient(
        ChatClientConfig(
            api_url="https://bothesis.example/",
            user_id="user-uuid",
            tenant_id="tenant-uuid",
            access_token="test-token",
        ),
        transport=httpx.MockTransport(handler),
    )

    received = [
        event
        async for event in client.stream_turn(
            message="Explain the documents.",
            conversation_id="f8383f55-174a-4d7e-a28a-68d767dcaeb5",
            history=[{"role": "user", "content": "Earlier question"}],
        )
    ]

    request = captured["request"]
    assert request.url == "https://bothesis.example/api/v1/agent/chat"
    assert request.headers["x-bothesis-user-id"] == "user-uuid"
    assert request.headers["x-bothesis-tenant-id"] == "tenant-uuid"
    assert request.headers["authorization"] == "Bearer test-token"
    assert json.loads(request.content) == {
        "message": "Explain the documents.",
        "conversation_id": "f8383f55-174a-4d7e-a28a-68d767dcaeb5",
        "history": [{"role": "user", "content": "Earlier question"}],
    }
    assert [event.event["type"] for event in received] == [
        "turn.started",
        "item.delta",
        "turn.completed",
    ]
    assert [event.raw_sse_line for event in received] == [
        lines[0],
        lines[2],
        lines[3],
    ]


@pytest.mark.asyncio
async def test_client_surfaces_http_rejection_detail() -> None:
    client = BothesisChatClient(
        ChatClientConfig(api_url="https://bothesis.example"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, text="active tenant required")
        ),
    )

    with pytest.raises(ChatRequestError, match="active tenant required"):
        async for _ in client.stream_turn(
            message="hello",
            conversation_id="f8383f55-174a-4d7e-a28a-68d767dcaeb5",
            history=[],
        ):
            pass


def test_state_projects_commentary_text_deltas_and_tool_lifecycle() -> None:
    state = ChatState(conversation_id="f8383f55-174a-4d7e-a28a-68d767dcaeb5")
    state.begin_turn("Explain the documents.")

    state.apply_event(
        {
            "type": "item.started",
            "item": {"type": "message", "id": "commentary-1", "content": []},
        },
        raw_sse_line='data: {"type":"item.started"}',
    )
    state.apply_event(
        {"type": "item.delta", "item_id": "commentary-1", "delta": "Searching knowledge..."},
        raw_sse_line='data: {"type":"item.delta"}',
    )
    state.apply_event(
        {
            "type": "item.completed",
            "item": {
                "type": "message",
                "id": "commentary-1",
                "phase": "commentary",
                "status": "completed",
                "content": [],
            },
        },
        raw_sse_line='data: {"type":"item.completed"}',
    )
    state.apply_event(
        {
            "type": "item.started",
            "item": {
                "type": "tool_call",
                "id": "tool-1",
                "call_id": "call-1",
                "name": "knowledge_search",
                "label": "Search knowledge base",
                "category": "retrieval",
                "status": "in_progress",
            },
        },
        raw_sse_line='data: {"type":"item.started"}',
    )
    state.apply_event(
        {
            "type": "item.completed",
            "item": {
                "type": "tool_result",
                "id": "result-1",
                "call_id": "call-1",
                "name": "knowledge_search",
                "status": "completed",
                "duration_ms": 12,
                "result_count": 2,
            },
        },
        raw_sse_line='data: {"type":"item.completed"}',
    )
    state.apply_event(
        {
            "type": "item.started",
            "item": {"type": "message", "id": "answer-1", "content": []},
        },
        raw_sse_line='data: {"type":"item.started"}',
    )
    state.apply_event(
        {"type": "item.delta", "item_id": "answer-1", "delta": "Grounded answer."},
        raw_sse_line='data: {"type":"item.delta"}',
    )
    state.apply_event(
        {
            "type": "item.completed",
            "item": {
                "type": "message",
                "id": "answer-1",
                "phase": "final_answer",
                "status": "completed",
                "content": [],
            },
        },
        raw_sse_line='data: {"type":"item.completed"}',
    )
    state.apply_event(
        {"type": "turn.completed"},
        raw_sse_line='data: {"type":"turn.completed"}',
    )
    state.complete_turn()

    assert state.turn is not None
    assert state.turn.commentary_text == "Searching knowledge..."
    assert state.turn.final_text == "Grounded answer."
    assert state.turn.activities["tool-1"].status == "completed"
    assert state.turn.activities["tool-1"].result_count == 2
    assert state.history == [
        type(state.history[0])("user", "Explain the documents."),
        type(state.history[0])("assistant", "Grounded answer."),
    ]


def test_state_clips_and_bounds_history_for_the_chat_api() -> None:
    state = ChatState(conversation_id="f8383f55-174a-4d7e-a28a-68d767dcaeb5")
    for index in range(13):
        state.history.extend([
            HistoryMessage("user", f"question-{index}"),
            HistoryMessage("assistant", "A" * 9_000),
        ])

    history = state.request_history()

    assert len(history) <= 24
    assert sum(len(entry.content) for entry in history) <= 24_000
    assert all(len(entry.content) <= 8_000 for entry in history)
    assert history[0].role == "user"
