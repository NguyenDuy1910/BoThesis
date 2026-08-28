from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.document_index import EmbeddingService


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


@pytest.mark.asyncio
async def test_openrouter_transport_implements_the_embedding_service_contract() -> None:
    seen_input: object | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_input
        seen_input = json.loads(request.content)["input"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [3, 4.5]},
                    {"index": 0, "embedding": [1.0, 2]},
                ]
            },
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = OpenRouterTransport(
        api_key="test-key",
        embedding_model="test-model",
        client=client,
    )

    assert isinstance(transport, EmbeddingService)
    assert transport.embedding_model == "test-model"
    assert await transport.embed_documents([" first ", "second"]) == [
        [1.0, 2.0],
        [3.0, 4.5],
    ]
    assert seen_input == ["first", "second"]

    await client.aclose()


@pytest.mark.asyncio
async def test_openrouter_query_embedding_validates_input_and_vector() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"embedding": [True]}]},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = OpenRouterTransport(
        api_key="test-key",
        embedding_model="test-model",
        client=client,
    )

    with pytest.raises(ValueError, match="query must not be empty"):
        await transport.embed_query("  ")
    with pytest.raises(ValueError, match="embedding response vector is invalid"):
        await transport.embed_query("policy")

    await client.aclose()
