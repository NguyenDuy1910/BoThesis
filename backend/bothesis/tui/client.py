"""HTTP and SSE boundary for the BoThesis terminal client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx


class ChatClientError(Exception):
    """Base error raised by the terminal client's API boundary."""


class ChatRequestError(ChatClientError):
    """An HTTP response rejected a chat turn."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Chat request failed ({status_code}): {detail}")


class ChatProtocolError(ChatClientError):
    """The chat endpoint returned a non-JSON SSE data frame."""


@dataclass(frozen=True, slots=True)
class ChatClientConfig:
    """Configuration passed directly to the already-running API service."""

    api_url: str = "http://127.0.0.1:8000"
    user_id: str | None = None
    tenant_id: str | None = None
    access_token: str | None = None


@dataclass(frozen=True, slots=True)
class ReceivedStreamEvent:
    """One parsed API event together with its original SSE data line."""

    event: Mapping[str, Any]
    raw_sse_line: str


class BothesisChatClient:
    """Stream public runtime events from ``POST /api/v1/agent/chat``.

    This class intentionally knows nothing about the in-process agent protocol.
    It only transports the API request and the JSON event envelopes emitted by
    the backend's SSE endpoint.
    """

    def __init__(
        self,
        config: ChatClientConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    async def stream_turn(
        self,
        *,
        message: str,
        conversation_id: str,
        history: Sequence[Mapping[str, str]],
    ) -> AsyncIterator[ReceivedStreamEvent]:
        """Yield API events in the exact order their SSE frames arrive."""

        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }
        if self._config.access_token:
            headers["Authorization"] = f"Bearer {self._config.access_token}"
        if self._config.user_id:
            headers["X-Bothesis-User-Id"] = self._config.user_id
        if self._config.tenant_id:
            headers["X-Bothesis-Tenant-Id"] = self._config.tenant_id

        payload = {
            "message": message,
            "conversation_id": conversation_id,
            "history": [dict(entry) for entry in history],
        }
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        async with httpx.AsyncClient(
            base_url=self._config.api_url.rstrip("/"),
            timeout=timeout,
            transport=self._transport,
        ) as client:
            async with client.stream(
                "POST",
                "/api/v1/agent/chat",
                headers=headers,
                json=payload,
            ) as response:
                if response.is_error:
                    detail = (await response.aread()).decode(errors="replace").strip()
                    raise ChatRequestError(response.status_code, detail or response.reason_phrase)
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type.lower():
                    raise ChatProtocolError(
                        "Chat endpoint did not return an SSE response "
                        f"(content type: {content_type or 'missing'})."
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:]
                    if data.startswith(" "):
                        data = data[1:]
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ChatProtocolError("Received an invalid agent stream event.") from exc
                    if not isinstance(event, dict):
                        raise ChatProtocolError("Received a non-object agent stream event.")
                    yield ReceivedStreamEvent(event=event, raw_sse_line=line)


__all__ = [
    "BothesisChatClient",
    "ChatClientConfig",
    "ChatClientError",
    "ChatProtocolError",
    "ChatRequestError",
    "ReceivedStreamEvent",
]
