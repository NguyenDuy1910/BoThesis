from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.transports.openai import OpenAITransport


def _response(output: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "created_at": 1,
        "model": "gpt-5.4-mini",
        "object": "response",
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": "completed",
        "usage": {
            "input_tokens": 4,
            "input_tokens_details": {
                "cached_tokens": 2,
                "cache_write_tokens": 0,
            },
            "output_tokens": 3,
            "output_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 7,
        },
    }


@pytest.mark.asyncio
async def test_responses_returns_native_function_call_and_forwards_native_inputs() -> (
    None
):
    seen_body: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json=_response(
                [
                    {
                        "id": "fc_1",
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "knowledge_search",
                        "arguments": '{"query":"leave policy"}',
                        "status": "completed",
                    }
                ]
            ),
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        http_client=http_client,
    )
    transport = OpenAITransport(model="gpt-5.4-mini", client=client)

    response = await transport.responses(
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Read these inputs"},
                    {
                        "type": "input_image",
                        "image_url": "https://files.example/image.png",
                        "detail": "auto",
                    },
                    {"type": "input_file", "file_id": "file_1"},
                ],
            }
        ],
        previous_response_id="resp_previous",
        reasoning={"effort": "low", "summary": "auto"},
        tools=[
            {
                "type": "function",
                "name": "knowledge_search",
                "description": "Search enterprise knowledge.",
                "parameters": {"type": "object"},
            }
        ],
    )

    assert isinstance(response.output[0], ResponseFunctionToolCall)
    assert response.output[0].call_id == "call_1"
    assert seen_body["previous_response_id"] == "resp_previous"
    assert seen_body["reasoning"] == {"effort": "low", "summary": "auto"}
    assert seen_body["input"][0]["content"][2] == {
        "type": "input_file",
        "file_id": "file_1",
    }
    await client.close()


@pytest.mark.asyncio
async def test_stream_response_exposes_typed_sdk_events() -> None:
    final_response = _response(
        [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Hello",
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        events = [
            {
                "type": "response.output_text.delta",
                "content_index": 0,
                "delta": "Hello",
                "item_id": "msg_1",
                "logprobs": [],
                "output_index": 0,
                "sequence_number": 1,
            },
            {
                "type": "response.completed",
                "response": final_response,
                "sequence_number": 2,
            },
        ]
        sse = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(
            200,
            text=sse,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        http_client=http_client,
    )
    transport = OpenAITransport(model="gpt-5.4-mini", client=client)

    stream = await transport.stream_response(input="Hello")
    events = [event async for event in stream]

    assert events[0].type == "response.output_text.delta"
    assert events[0].delta == "Hello"
    assert events[1].type == "response.completed"
    assert events[1].response.output_text == "Hello"
    await client.close()


@pytest.mark.asyncio
async def test_parse_response_uses_the_sdk_structured_output_parser() -> None:
    class Summary(BaseModel):
        summary: str

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["text"]["format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json=_response(
                [
                    {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"summary":"Grounded result"}',
                                "annotations": [],
                                "logprobs": [],
                            }
                        ],
                    }
                ]
            ),
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        http_client=http_client,
    )
    transport = OpenAITransport(model="gpt-5.4-mini", client=client)

    response = await transport.parse_response(
        input="Summarize",
        text_format=Summary,
    )

    assert response.output_parsed == Summary(summary="Grounded result")
    await client.close()


@pytest.mark.asyncio
async def test_embeddings_and_files_return_native_sdk_objects() -> None:
    file_object = {
        "id": "file_1",
        "bytes": 3,
        "created_at": 1,
        "filename": "input.txt",
        "object": "file",
        "purpose": "user_data",
        "status": "processed",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/embeddings":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"embedding": [0.1, 0.2], "index": 0, "object": "embedding"}
                    ],
                    "model": "text-embedding-3-small",
                    "object": "list",
                    "usage": {"prompt_tokens": 2, "total_tokens": 2},
                },
                request=request,
            )
        if path == "/v1/files" and request.method == "GET":
            return httpx.Response(
                200,
                json={"object": "list", "data": [file_object], "has_more": False},
                request=request,
            )
        if path == "/v1/files" and request.method == "POST":
            return httpx.Response(200, json=file_object, request=request)
        if path == "/v1/files/file_1/content":
            return httpx.Response(200, content=b"abc", request=request)
        if path == "/v1/files/file_1" and request.method == "DELETE":
            return httpx.Response(
                200,
                json={"id": "file_1", "deleted": True, "object": "file"},
                request=request,
            )
        return httpx.Response(200, json=file_object, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        http_client=http_client,
    )
    transport = OpenAITransport(
        model="gpt-5.4-mini",
        embedding_model="text-embedding-3-small",
        client=client,
    )

    embedding = await transport.embeddings(input="annual leave")
    uploaded = await transport.upload_file(
        file=("input.txt", b"abc", "text/plain"),
        purpose="user_data",
    )
    retrieved = await transport.retrieve_file("file_1")
    files = await transport.list_files()
    content = await transport.file_content("file_1")
    deleted = await transport.delete_file("file_1")

    assert embedding.data[0].embedding == [0.1, 0.2]
    assert uploaded.id == retrieved.id == files.data[0].id == "file_1"
    assert content.content == b"abc"
    assert deleted.deleted is True
    await client.close()
