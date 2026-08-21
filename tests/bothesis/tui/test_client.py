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
        'data: {"type":"response.created","sequence_number":1,"response_id":"resp-1","response":{"id":"resp-1","status":"in_progress"}}',
        ': ignored SSE comment',
        'data: {"type":"response.completed","sequence_number":2,"response":{"id":"resp-1","status":"completed"}}',
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
        "response.created",
        "response.completed",
    ]
    assert [event.raw_sse_line for event in received] == [
        lines[0],
        lines[2],
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


def test_state_materializes_response_items_and_deduplicates_sequences() -> None:
    state = ChatState(conversation_id="f8383f55-174a-4d7e-a28a-68d767dcaeb5")
    state.begin_turn("Explain the documents.")
    events = [
        {"type": "response.created", "sequence_number": 1, "response_id": "resp-1", "response": {"id": "resp-1", "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 2, "response_id": "resp-1", "output_index": 0, "item": {"type": "message", "id": "message-1", "role": "assistant", "content": []}},
        {"type": "response.content_part.added", "sequence_number": 3, "response_id": "resp-1", "item_id": "message-1", "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": ""}},
        {"type": "response.output_text.delta", "sequence_number": 4, "response_id": "resp-1", "item_id": "message-1", "output_index": 0, "content_index": 0, "delta": "Grounded "},
        {"type": "response.output_text.annotation.added", "sequence_number": 5, "response_id": "resp-1", "item_id": "message-1", "output_index": 0, "content_index": 0, "annotation": {"type": "citation", "citation": {"id": "ev-1"}}},
        {"type": "response.output_text.done", "sequence_number": 6, "response_id": "resp-1", "item_id": "message-1", "output_index": 0, "content_index": 0, "text": "Grounded answer."},
        {"type": "response.output_item.done", "sequence_number": 7, "response_id": "resp-1", "output_index": 0, "item": {"type": "message", "id": "message-1", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "Grounded answer.", "annotations": [{"type": "citation", "citation": {"id": "ev-1"}}]}]}},
        {"type": "response.completed", "sequence_number": 8, "response": {"id": "resp-1", "status": "completed"}},
        {"type": "response.output_text.delta", "sequence_number": 8, "response_id": "resp-1", "item_id": "message-1", "output_index": 0, "content_index": 0, "delta": "ignored"},
    ]
    for event in events:
        state.apply_event(event, raw_sse_line=json.dumps(event))
    state.complete_turn()

    assert state.turn is not None
    assert state.turn.final_text == "Grounded answer."
    assert state.turn.responses["resp-1"].items["message-1"].content[0]["annotations"][0]["citation"]["id"] == "ev-1"
    assert state.turn.last_sequence_number == 8
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
