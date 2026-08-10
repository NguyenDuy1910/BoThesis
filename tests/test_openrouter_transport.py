from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import TextDelta, TurnDone
from bothesis.agent.transports.openrouter import OpenRouterTransport


@pytest.mark.asyncio
async def test_stream_turn_requests_and_normalizes_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["usage"] == {"include": True}
        stream = (
            'data: {"model":"openai/gpt-5.4-mini","choices":'
            '[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"model":"openai/gpt-5.4-mini","choices":'
            '[{"delta":{},"finish_reason":"stop"}],"usage":'
            '{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15,'
            '"prompt_tokens_details":{"cached_tokens":8},"cost":0.001}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenRouterTransport(
            api_key="test-key",
            model="openai/gpt-5.4-mini",
            client=client,
        )
        events = [
            event
            async for event in transport.stream_turn(
                [{"role": "user", "content": "Hello"}],
            )
        ]

    assert events[0] == TextDelta("Hello")
    assert events[1] == TurnDone(
        finish_reason="stop",
        model="openai/gpt-5.4-mini",
        usage={
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
            "cached_prompt_tokens": 8,
        },
    )
    assert len(events) == 2
