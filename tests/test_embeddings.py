from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.transports.openrouter import OpenRouterTransport


@pytest.mark.asyncio
async def test_openrouter_embeddings_returns_the_native_payload() -> None:
    seen_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2]}]},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = OpenRouterTransport(
        api_key="test-key",
        embedding_model="openai/text-embedding-3-small",
        client=client,
    )

    response = await transport.embeddings(input="annual leave")

    assert response == {"data": [{"embedding": [0.1, 0.2]}]}
    assert seen_request is not None
    assert seen_request.url.path == "/api/v1/embeddings"
    assert json.loads(seen_request.content) == {
        "model": "openai/text-embedding-3-small",
        "input": "annual leave",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_openrouter_embeddings_does_not_normalize_provider_data() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{}]}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = OpenRouterTransport(
        api_key="test-key",
        embedding_model="test-model",
        client=client,
    )

    response = await transport.embeddings(input=["annual leave"])

    assert response == {"data": [{}]}

    await client.aclose()
