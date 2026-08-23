"""OpenRouter embedding adapter for document indexing and retrieval."""

from __future__ import annotations

import math
import os
from typing import Any

from bothesis.agent.transports.openrouter import OpenRouterTransport


class OpenRouterEmbeddingService:
    """Expose validated vectors through the document-index embedding contract."""

    def __init__(self, *, base_url: str) -> None:
        self.model = os.getenv("EMBEDDING_MODEL", "").strip()
        self._base_url = base_url
        self._client: Any | None = None

    async def embed_query(self, query: str) -> list[float]:
        normalized = query.strip()
        if not normalized:
            raise ValueError("query must not be empty")
        return (await self._embed([normalized]))[0]

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        normalized = [document.strip() for document in documents]
        if not normalized or any(not document for document in normalized):
            raise ValueError("documents must contain non-empty text")
        return await self._embed(normalized)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = OpenRouterTransport(
                base_url=self._base_url,
                embedding_model=self.model or None,
            )
            self.model = self._client.embedding_model or ""
        return self._client

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        payload = await self._get_client().embeddings(
            input=inputs[0] if len(inputs) == 1 else inputs,
        )
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(inputs):
            raise ValueError("embedding response does not contain all vectors")
        indexed: list[tuple[int, list[float]]] = []
        for fallback_index, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError("embedding response vector is invalid")
            raw_vector = item.get("embedding")
            if not isinstance(raw_vector, list) or not raw_vector:
                raise ValueError("embedding response vector is invalid")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in raw_vector
            ):
                raise ValueError("embedding response vector is invalid")
            vector = [float(value) for value in raw_vector]
            if any(not math.isfinite(value) for value in vector):
                raise ValueError("embedding response vector is invalid")
            raw_index = item.get("index", fallback_index)
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise ValueError("embedding response index is invalid")
            indexed.append((raw_index, vector))
        indexed.sort(key=lambda item: item[0])
        if [index for index, _ in indexed] != list(range(len(inputs))):
            raise ValueError("embedding response indexes are invalid")
        return [vector for _, vector in indexed]


__all__ = ["OpenRouterEmbeddingService"]
