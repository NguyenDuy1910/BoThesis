from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from textual.widgets import TextArea

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from bothesis.tui.app import BothesisTui
import bothesis.tui.app as tui_app
from bothesis.tui.client import BothesisChatClient, ChatClientConfig


@pytest.mark.asyncio
async def test_tui_renders_a_streamed_answer_and_keeps_turn_history() -> None:
    stream = "\n".join([
        'data: {"type":"response.created","sequence_number":1,"response_id":"resp-1","response":{"id":"resp-1","status":"in_progress"}}',
        'data: {"type":"response.output_item.added","sequence_number":2,"response_id":"resp-1","output_index":0,"item":{"type":"message","id":"message-1","role":"assistant","content":[]}}',
        'data: {"type":"response.content_part.added","sequence_number":3,"response_id":"resp-1","item_id":"message-1","output_index":0,"content_index":0,"part":{"type":"output_text","text":""}}',
        'data: {"type":"response.output_text.delta","sequence_number":4,"response_id":"resp-1","item_id":"message-1","output_index":0,"content_index":0,"delta":"Grounded **answer**"}',
        'data: {"type":"response.output_item.done","sequence_number":5,"response_id":"resp-1","output_index":0,"item":{"type":"message","id":"message-1","role":"assistant","status":"completed","content":[{"type":"output_text","text":"Grounded **answer**"}]}}',
        'data: {"type":"response.completed","sequence_number":6,"response":{"id":"resp-1","status":"completed"}}',
    ]) + "\n\n"
    app = BothesisTui(ChatClientConfig())
    app._client = BothesisChatClient(
        ChatClientConfig(api_url="http://test"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=stream,
            )
        ),
    )

    async with app.run_test() as pilot:
        app.query_one("#composer", TextArea).load_text("What is the answer?")
        app.action_send()
        await pilot.pause(0.2)

    assert [entry.content for entry in app._state.history] == [
        "What is the answer?",
        "Grounded **answer**",
    ]
    assert app._state.raw_sse_lines[-1] == 'data: {"type":"response.completed","sequence_number":6,"response":{"id":"resp-1","status":"completed"}}'


def test_tui_uses_the_local_streaming_test_user_by_default(monkeypatch) -> None:
    captured: dict[str, ChatClientConfig] = {}

    class StubTui:
        def __init__(self, config: ChatClientConfig, **_: object) -> None:
            captured["config"] = config

        def run(self) -> None:
            return None

    monkeypatch.setenv("BOTHESIS_USER_ID", "")
    monkeypatch.setattr(tui_app, "BothesisTui", StubTui)

    tui_app.run_tui([])

    assert captured["config"].user_id == tui_app.DEFAULT_DEVELOPMENT_USER_ID
