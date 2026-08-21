"""Thin async boundary over OpenRouter's native API.

OpenRouter serves ``POST /responses`` in OpenResponses format and is
OpenAI-compatible on the wire, so the model path is the official OpenAI SDK
pointed at OpenRouter's base URL. That keeps this class thin — no hand-rolled
SSE reader, no chat-completions reconstruction — and gives the agent one set of
transport error types for every provider, which is what
:mod:`bothesis.agent.sampling` classifies for retries.

Three things are genuinely OpenRouter-specific and are normalized here:

* the base URL and the optional ``HTTP-Referer`` / ``X-Title`` attribution
  headers;
* request options outside the specification (``provider`` routing preferences,
  ``plugins``, ``top_k``, ``models``, ``session_id``, …), which ride in
  ``extra_body`` and are therefore never named by the agent; and
* embeddings, which are a separate API with a separate client and a raw payload
  contract, deliberately not routed through the Responses client.
"""

from __future__ import annotations

import os
from typing import Any, cast

import httpx
from openai import AsyncOpenAI, AsyncStream
from openai.types.responses import (
    Response,
    ResponseInputParam,
    ResponseStreamEvent,
)


class OpenRouterTransport:
    """Expose OpenRouter Responses and embeddings without normalization."""

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
        responses_client: AsyncOpenAI | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL")
        self.embedding_model = embedding_model or os.getenv("EMBEDDING_MODEL")
        if not self.api_key:
            raise ValueError("OpenRouter API key is required")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        attribution: dict[str, str] = {}
        if site_url:
            attribution["HTTP-Referer"] = site_url
        if app_name:
            attribution["X-Title"] = app_name
        self._headers.update(attribution)
        self._attribution = attribution
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        # Built on first model call: a transport created only for embeddings
        # should not open a second connection pool it never uses.
        self._responses_client = responses_client
        self._owns_responses_client = responses_client is None

    def _responses(self) -> AsyncOpenAI:
        if self._responses_client is None:
            self._responses_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self._base_url,
                default_headers=self._attribution or None,
                timeout=self._timeout,
            )
        return self._responses_client

    async def responses(
        self,
        *,
        input: str | ResponseInputParam,
        model: str | None = None,
        **params: Any,
    ) -> Response:
        """Create a non-streaming response and return the payload unchanged."""

        if "stream" in params:
            raise ValueError("use stream_response for streaming Responses requests")
        response = await self._responses().responses.create(
            model=self._model(model),
            input=input,
            **params,
        )
        return cast(Response, response)

    async def stream_response(
        self,
        *,
        input: str | ResponseInputParam,
        model: str | None = None,
        **params: Any,
    ) -> AsyncStream[ResponseStreamEvent]:
        """Create a streaming response over OpenRouter's OpenResponses endpoint."""

        if "stream" in params:
            raise ValueError("stream_response controls the stream parameter")
        stream = await self._responses().responses.create(
            model=self._model(model),
            input=input,
            stream=True,
            **params,
        )
        return cast(AsyncStream[ResponseStreamEvent], stream)

    async def embeddings(
        self,
        *,
        input: object,
        model: str | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        """Return one native OpenRouter embedding payload.

        Embeddings stay on their own HTTP client and keep their raw payload
        contract: they are a different API from the model path and share none of
        its semantics.
        """

        selected_model = model or self.embedding_model
        if not selected_model:
            raise ValueError("OpenRouter embedding model is required")
        response = await self._client.post(
            f"{self._base_url}/embeddings",
            headers=self._headers,
            json={"model": selected_model, "input": input, **params},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("OpenRouter returned a non-object response")
        return payload

    async def aclose(self) -> None:
        """Close the internally-created clients when the app shuts down."""

        if self._owns_client:
            await self._client.aclose()
        if self._owns_responses_client and self._responses_client is not None:
            await self._responses_client.close()

    def _model(self, model: str | None) -> str:
        selected_model = model or self.model
        if not selected_model:
            raise ValueError("OpenRouter model is required")
        return selected_model


__all__ = ["OpenRouterTransport"]
