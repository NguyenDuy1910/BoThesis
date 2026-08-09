"""OpenRouter implementation of the agent transport contracts."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, Mapping, Sequence

import httpx

from bothesis.agent.models import TextDelta, ToolCallDelta, TurnDone

from .base import ChatMessage, LLMResponse, LLMTransport, LLMTransportError


class OpenRouterTransport(LLMTransport):
    """Async transport for OpenRouter's OpenAI-compatible APIs."""

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        site_url: str | None = None,
        app_name: str | None = None,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL")
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

    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        selected_model = model or self.model
        if not messages:
            raise ValueError("messages must not be empty")
        if not selected_model:
            raise ValueError("model is required")
        body: dict[str, Any] = {
            "model": selected_model,
            "messages": [
                message.as_dict() if isinstance(message, ChatMessage) else dict(message)
                for message in messages
            ],
        }
        optional = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "tools": list(tools) if tools is not None else None,
            "tool_choice": tool_choice,
        }
        body.update({key: value for key, value in optional.items() if value is not None})
        if extra_body:
            body.update(extra_body)
        payload = await self.chat_completions(body)
        try:
            choice = payload["choices"][0]
            message = choice["message"]
            usage = payload.get("usage") or {}
            return LLMResponse(
                id=payload["id"],
                model=payload.get("model", selected_model),
                content=message.get("content"),
                finish_reason=choice.get("finish_reason"),
                tool_calls=tuple(message.get("tool_calls") or ()),
                usage={key: int(value) for key, value in usage.items() if isinstance(value, (int, float))},
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMTransportError("OpenRouter returned an unexpected completion shape") from exc

    async def chat_completions(self, body: dict[str, Any]) -> dict[str, Any]:
        """Make one non-streaming OpenRouter chat-completions request."""
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMTransportError("OpenRouter chat completion request failed") from exc
        if not isinstance(payload, dict):
            raise LLMTransportError("OpenRouter returned a non-object completion")
        return payload

    async def stream_turn(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[TextDelta | ToolCallDelta | TurnDone]:
        """Normalize OpenRouter SSE into a single model-turn event stream."""
        selected_model = model or self.model
        if not messages:
            raise ValueError("messages must not be empty")
        if not selected_model:
            raise ValueError("model is required")
        body: dict[str, Any] = {
            "model": selected_model,
            "messages": [
                message.as_dict() if isinstance(message, ChatMessage) else dict(message)
                for message in messages
            ],
        }
        optional = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": list(tools) if tools is not None else None,
            "tool_choice": tool_choice,
        }
        body.update({key: value for key, value in optional.items() if value is not None})
        if extra_body:
            body.update(extra_body)
        body["stream"] = True

        tool_calls: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        emitted_done = False
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw_data = line[5:].lstrip()
                    if raw_data == "[DONE]":
                        if not emitted_done:
                            yield TurnDone(
                                finish_reason=finish_reason or "stop",
                                tool_calls=_assembled_tool_calls(tool_calls),
                            )
                        return
                    try:
                        payload = json.loads(raw_data)
                    except json.JSONDecodeError as exc:
                        raise LLMTransportError("OpenRouter returned invalid stream data") from exc
                    if not isinstance(payload, Mapping):
                        raise LLMTransportError("OpenRouter returned invalid stream data")
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, Mapping):
                        continue
                    delta = choice.get("delta")
                    if isinstance(delta, Mapping):
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            yield TextDelta(content)
                        raw_calls = delta.get("tool_calls")
                        if isinstance(raw_calls, list):
                            for position, raw_call in enumerate(raw_calls):
                                if not isinstance(raw_call, Mapping):
                                    continue
                                index = _tool_call_index(raw_call.get("index"), position)
                                pending = tool_calls.setdefault(
                                    index,
                                    {
                                        "id": "",
                                        "name": "",
                                        "arguments": "",
                                    },
                                )
                                raw_call_id = raw_call.get("id")
                                if isinstance(raw_call_id, str) and raw_call_id:
                                    pending["id"] = raw_call_id
                                function = raw_call.get("function")
                                if not isinstance(function, Mapping):
                                    function = {}
                                name = function.get("name")
                                arguments = function.get("arguments")
                                name_delta = name if isinstance(name, str) else ""
                                argument_delta = arguments if isinstance(arguments, str) else ""
                                pending["name"] += name_delta
                                pending["arguments"] += argument_delta
                                if pending["id"] and (name_delta or argument_delta):
                                    yield ToolCallDelta(
                                        call_id=pending["id"],
                                        name=name_delta,
                                        arguments=argument_delta,
                                    )
                    raw_finish_reason = choice.get("finish_reason")
                    if raw_finish_reason is not None:
                        finish_reason = str(raw_finish_reason)
                        yield TurnDone(
                            finish_reason=finish_reason,
                            tool_calls=_assembled_tool_calls(tool_calls),
                        )
                        emitted_done = True
        except httpx.HTTPError as exc:
            raise LLMTransportError("OpenRouter stream request failed") from exc

        if not emitted_done:
            yield TurnDone(
                finish_reason=finish_reason or "stop",
                tool_calls=_assembled_tool_calls(tool_calls),
            )

    async def aclose(self) -> None:
        """Close the internally-created HTTP client when the app shuts down."""
        if self._owns_client:
            await self._client.aclose()


def _tool_call_index(raw_index: Any, fallback: int) -> int:
    try:
        return int(raw_index)
    except (TypeError, ValueError):
        return fallback


def _assembled_tool_calls(tool_calls: Mapping[int, Mapping[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "id": tool_call["id"] or f"call_{index}",
            "type": "function",
            "function": {
                "name": tool_call["name"],
                "arguments": tool_call["arguments"],
            },
        }
        for index, tool_call in sorted(tool_calls.items())
    ]


   
