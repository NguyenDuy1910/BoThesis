from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.transports.openrouter_embeddings import (
    EmbeddingError,
    OpenRouterEmbeddingClient,
)


@pytest.mark.asyncio
async def test_openrouter_embedder_posts_the_configured_model_and_normalizes_vector() -> None:
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
    embedder = OpenRouterEmbeddingClient(
        api_key="test-key",
        model="openai/text-embedding-3-small",
        client=client,
    )

    vector = await embedder.embed_query("annual leave")

    assert vector == [0.1, 0.2]
    assert seen_request is not None
    assert seen_request.url.path == "/api/v1/embeddings"
    assert json.loads(seen_request.content) == {
        "model": "openai/text-embedding-3-small",
        "input": "annual leave",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_openrouter_embedder_rejects_malformed_responses() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{}]}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    embedder = OpenRouterEmbeddingClient(api_key="test-key", model="test-model", client=client)

    with pytest.raises(EmbeddingError, match="embedding request failed"):
        await embedder.embed_query("annual leave")

    await client.aclose()
