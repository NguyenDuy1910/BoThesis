"""Thin async boundary over OpenRouter's native HTTP API."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from time import time_ns
from typing import Any

import httpx

_log = logging.getLogger(__name__)


class OpenRouterTransport:
    """Expose OpenRouter chat and embeddings without response wrappers."""

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    provider = "openrouter"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        site_url: str | None = None,
        app_name: str | None = None,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL")
        self.embedding_model = embedding_model or os.getenv("EMBEDDING_MODEL")
        if not self.api_key:
            raise ValueError("OpenRouter API key is required")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if site_url:
            self._headers["HTTP-Referer"] = site_url
        if app_name:
            self._headers["X-Title"] = app_name

    async def chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        model: str | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        """Return one native OpenRouter chat-completion payload."""

        body = self._chat_body(messages=messages, model=model, params=params)
        if "stream" in body:
            raise ValueError("use stream_chat for streaming chat requests")
        return await self._post_json("/chat/completions", body)

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        model: str | None = None,
        **params: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield OpenRouter's JSON stream chunks without reconstructing them."""

        body = self._chat_body(messages=messages, model=model, params=params)
        if "stream" in body:
            raise ValueError("stream_chat controls the stream parameter")
        body["stream"] = True

        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json=body,
        ) as response:
            response.raise_for_status()
            data_lines: list[str] = []
            native_chunk_sequence = 0
            text_delta_sequence = 0
            async for line in response.aiter_lines():
                if not line:
                    if data_lines:
                        payload = self._stream_payload(data_lines)
                        data_lines.clear()
                        if payload is None:
                            return
                        native_chunk_sequence += 1
                        text_characters = self._text_delta_characters(payload)
                        if text_characters:
                            text_delta_sequence += 1
                        _log.debug(
                            "stream_timing boundary=native_provider_chunk_received "
                            "at_unix_ms=%d native_chunk_sequence=%d "
                            "text_delta_sequence=%s text_characters=%d",
                            time_ns() // 1_000_000,
                            native_chunk_sequence,
                            text_delta_sequence if text_characters else "-",
                            text_characters,
                        )
                        yield payload
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if data_lines:
                payload = self._stream_payload(data_lines)
                if payload is not None:
                    native_chunk_sequence += 1
                    text_characters = self._text_delta_characters(payload)
                    if text_characters:
                        text_delta_sequence += 1
                    _log.debug(
                        "stream_timing boundary=native_provider_chunk_received "
                        "at_unix_ms=%d native_chunk_sequence=%d "
                        "text_delta_sequence=%s text_characters=%d",
                        time_ns() // 1_000_000,
                        native_chunk_sequence,
                        text_delta_sequence if text_characters else "-",
                        text_characters,
                    )
                    yield payload

    async def embeddings(
        self,
        *,
        input: object,
        model: str | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        """Return one native OpenRouter embedding payload."""

        selected_model = model or self.embedding_model
        if not selected_model:
            raise ValueError("OpenRouter embedding model is required")
        return await self._post_json(
            "/embeddings",
            {"model": selected_model, "input": input, **params},
        )

    async def aclose(self) -> None:
        """Close the internally-created HTTP client when the app shuts down."""
        if self._owns_client:
            await self._client.aclose()

    def _chat_body(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        model: str | None,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not messages:
            raise ValueError("messages must not be empty")
        selected_model = model or self.model
        if not selected_model:
            raise ValueError("OpenRouter model is required")
        return {
            "model": selected_model,
            "messages": [dict(message) for message in messages],
            **params,
        }

    async def _post_json(
        self,
        path: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"{self._base_url}{path}",
            headers=self._headers,
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("OpenRouter returned a non-object response")
        return payload

    @staticmethod
    def _text_delta_characters(payload: Mapping[str, Any]) -> int:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return 0
        choice = choices[0]
        if not isinstance(choice, Mapping):
            return 0
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            return 0
        content = delta.get("content")
        return len(content) if isinstance(content, str) else 0

    @staticmethod
    def _stream_payload(data_lines: Sequence[str]) -> dict[str, Any] | None:
        raw_data = "\n".join(data_lines)
        if raw_data == "[DONE]":
            return None
        payload = json.loads(raw_data)
        if not isinstance(payload, dict):
            raise ValueError("OpenRouter returned a non-object stream chunk")
        return payload


__all__ = ["OpenRouterTransport"]
