from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.transports.openrouter import OpenRouterTransport


@pytest.mark.asyncio
async def test_stream_chat_yields_native_chunks_and_ignores_sse_comments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {
            "model": "openai/gpt-5.4-mini",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        stream = (
            ": OPENROUTER PROCESSING\n\n"
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
        chunks = [
            chunk
            async for chunk in transport.stream_chat(
                messages=[{"role": "user", "content": "Hello"}],
            )
        ]

    assert chunks == [
        {
            "model": "openai/gpt-5.4-mini",
            "choices": [{"delta": {"content": "Hello"}}],
        },
        {
            "model": "openai/gpt-5.4-mini",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "total_tokens": 15,
                "prompt_tokens_details": {"cached_tokens": 8},
                "cost": 0.001,
            },
        },
    ]


@pytest.mark.asyncio
async def test_stream_chat_preserves_native_reasoning_metadata() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        stream = (
            'data: {"choices":[{"delta":{"reasoning":"raw chain",'
            '"reasoning_details":['
            '{"type":"reasoning.summary","summary":"Compared the constraints."},'
            '{"type":"reasoning.text","text":"private step-by-step reasoning"},'
            '{"type":"reasoning.encrypted","data":"secret"}'
            "]}}]}\n\n"
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenRouterTransport(
            api_key="test-key",
            model="openai/gpt-5.4-mini",
            client=client,
        )
        chunks = [
            chunk
            async for chunk in transport.stream_chat(
                messages=[{"role": "user", "content": "Compare"}],
            )
        ]

    assert chunks[0]["choices"][0]["delta"]["reasoning"] == "raw chain"
    assert chunks[0]["choices"][0]["delta"]["reasoning_details"] == [
        {"type": "reasoning.summary", "summary": "Compared the constraints."},
        {"type": "reasoning.text", "text": "private step-by-step reasoning"},
        {"type": "reasoning.encrypted", "data": "secret"},
    ]
    assert chunks[1] == {"choices": [{"delta": {}, "finish_reason": "stop"}]}


@pytest.mark.asyncio
async def test_stream_chat_preserves_native_file_annotations() -> None:
    annotation = {
        "type": "file",
        "file": {
            "hash": "provider-file-hash",
            "name": "report.pdf",
            "content": [{"type": "text", "text": "Parsed report"}],
        },
    }

    def handler(_: httpx.Request) -> httpx.Response:
        stream = (
            f"data: {json.dumps({'choices': [{'delta': {'content': 'Done', 'annotations': [annotation]}}]})}\n\n"
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = OpenRouterTransport(
            api_key="test-key",
            model="openai/gpt-5.4-mini",
            client=client,
        )
        chunks = [
            chunk
            async for chunk in transport.stream_chat(
                messages=[{"role": "user", "content": "Summarize the PDF"}],
            )
        ]

    assert chunks[0]["choices"][0]["delta"] == {
        "content": "Done",
        "annotations": [annotation],
    }
