"""OpenRouter embedding transport used by semantic knowledge retrieval."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping

import httpx


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider cannot produce a usable vector."""


class OpenRouterEmbeddingClient:
    """OpenRouter adapter for the configured query-embedding model."""

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("EMBEDDING_MODEL")
        if not self._api_key:
            raise ValueError("OpenRouter API key is required")
        if not self.model:
            raise ValueError("embedding model is required")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def embed_query(self, query: str) -> list[float]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")

        try:
            response = await self._client.post(
                f"{self._base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": normalized_query},
            )
            response.raise_for_status()
            vector = _response_vector(response.json())
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise EmbeddingError("embedding request failed") from error

        return vector

    async def aclose(self) -> None:
        """Close the owned HTTP client when the application shuts down."""
        if self._owns_client:
            await self._client.aclose()


def _response_vector(payload: object) -> list[float]:
    if not isinstance(payload, Mapping):
        raise ValueError("embedding response must be an object")
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], Mapping):
        raise ValueError("embedding response does not contain a vector")
    raw_vector = data[0].get("embedding")
    if not isinstance(raw_vector, list) or not raw_vector:
        raise ValueError("embedding response vector is invalid")

    vector: list[float] = []
    for value in raw_vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("embedding response vector is invalid")
        coordinate = float(value)
        if not math.isfinite(coordinate):
            raise ValueError("embedding response vector is invalid")
        vector.append(coordinate)
    return vector

__all__ = ["EmbeddingError", "OpenRouterEmbeddingClient"]
