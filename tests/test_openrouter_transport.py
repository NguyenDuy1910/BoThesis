"""Transport-level tests for OpenRouter's OpenResponses endpoint.

OpenRouter documents ``POST /responses`` as "using OpenResponses API format" and
is OpenAI-compatible on the wire, so the transport's whole job is the three
things that are genuinely OpenRouter-specific: the base URL, the attribution
headers, and request options outside the specification.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.transports.openrouter import OpenRouterTransport

_RESPONSE_BODY = {
    "id": "resp_1",
    "object": "response",
    "created_at": 1,
    "status": "completed",
    "model": "openai/gpt-test",
    "output": [],
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
}

_STREAM_BODY = "\n".join(
    [
        'data: {"type":"response.output_text.delta","sequence_number":1,'
        '"item_id":"msg_1","output_index":0,"content_index":0,"delta":"Hi",'
        '"logprobs":[]}',
        "",
        'data: {"type":"response.completed","sequence_number":2,"response":'
        + json.dumps(_RESPONSE_BODY)
        + "}",
        "",
        "data: [DONE]",
        "",
    ]
)


def transport_with(
    handler: Any, *, site_url: str | None = None, app_name: str | None = None
) -> OpenRouterTransport:
    return OpenRouterTransport(
        api_key="test-key",
        model="openai/gpt-test",
        site_url=site_url,
        app_name=app_name,
        responses_client=AsyncOpenAI(
            api_key="test-key",
            base_url=OpenRouterTransport.DEFAULT_BASE_URL,
            default_headers=(
                {
                    key: value
                    for key, value in (
                        ("HTTP-Referer", site_url),
                        ("X-Title", app_name),
                    )
                    if value
                }
                or None
            ),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )


@pytest.mark.asyncio
async def test_stream_response_posts_to_the_openresponses_endpoint() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_STREAM_BODY,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    transport = transport_with(
        handler, site_url="https://bothesis.test", app_name="BoThesis"
    )
    stream = await transport.stream_response(
        input=[{"type": "message", "role": "user", "content": "hi"}],
        instructions="be brief",
        extra_body={"provider": {"order": ["openai"]}, "top_k": 40},
    )
    events = [event async for event in stream]

    assert seen["url"] == "https://openrouter.ai/api/v1/responses"
    assert seen["headers"]["http-referer"] == "https://bothesis.test"
    assert seen["headers"]["x-title"] == "BoThesis"
    # Specified fields are top-level; non-specified options merge in from
    # ``extra_body`` without the agent ever naming them.
    assert seen["body"]["model"] == "openai/gpt-test"
    assert seen["body"]["stream"] is True
    assert seen["body"]["instructions"] == "be brief"
    assert seen["body"]["provider"] == {"order": ["openai"]}
    assert seen["body"]["top_k"] == 40
    # Native OpenResponses events arrive typed and in order.
    assert [event.type for event in events] == [
        "response.output_text.delta",
        "response.completed",
    ]
    assert events[0].delta == "Hi"


@pytest.mark.asyncio
async def test_stream_response_yields_each_event_as_it_arrives() -> None:
    """The transport must not accumulate the stream before yielding."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=_STREAM_BODY,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    transport = transport_with(handler)
    stream = await transport.stream_response(input="hi")
    first = await anext(aiter(stream))

    assert first.type == "response.output_text.delta"
    assert first.delta == "Hi"


@pytest.mark.asyncio
async def test_a_non_streaming_response_returns_the_payload_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content).get("stream") is None
        return httpx.Response(200, json=_RESPONSE_BODY, request=request)

    response = await transport_with(handler).responses(input="hi")

    assert response.id == "resp_1"
    assert response.status == "completed"


@pytest.mark.asyncio
async def test_the_streaming_and_non_streaming_paths_reject_a_manual_stream_flag() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent")

    transport = transport_with(handler)

    with pytest.raises(ValueError, match="stream_response controls"):
        await transport.stream_response(input="hi", stream=True)
    with pytest.raises(ValueError, match="use stream_response"):
        await transport.responses(input="hi", stream=True)


@pytest.mark.asyncio
async def test_a_missing_model_is_rejected_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent")

    transport = OpenRouterTransport(
        api_key="test-key",
        responses_client=AsyncOpenAI(
            api_key="test-key",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )

    with pytest.raises(ValueError, match="OpenRouter model is required"):
        await transport.stream_response(input="hi")


def test_an_api_key_is_required() -> None:
    with pytest.raises(ValueError, match="OpenRouter API key is required"):
        OpenRouterTransport(api_key="")


def test_the_responses_client_is_not_built_for_an_embeddings_only_transport() -> None:
    """An embeddings-only transport must not open a second connection pool."""

    transport = OpenRouterTransport(
        api_key="test-key",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ),
    )

    assert transport._responses_client is None
