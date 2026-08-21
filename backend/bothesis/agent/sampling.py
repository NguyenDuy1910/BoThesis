"""Run one sampling request, retrying only transient transport failures.

A retry repeats the identical request because the transport failed in a way that
carried no model output — a dropped connection, a rate limit, a 5xx. It is never
a turn continuation: continuing because tool results now exist is the
:class:`~bothesis.agent.conversation_loop.ConversationLoop`'s job.

Once any canonical event has reached the caller the request is no longer
retryable, because the client has already observed part of that response.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAIError,
    RateLimitError,
)

from bothesis.agent import AgentExecutionError
from bothesis.agent.protocol import ResponseRequest, ResponseStreamEvent
from bothesis.agent.transports import ResponseStream

_RETRYABLE_OPENAI_ERRORS: tuple[type[Exception], ...] = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
_RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


async def sample(
    transport: ResponseStream,
    request: ResponseRequest,
    *,
    max_retries: int,
    retry_base_delay_seconds: float,
) -> AsyncIterator[ResponseStreamEvent]:
    """Stream one sampling request's canonical events, retrying transient loss."""

    attempt = 0
    while True:
        emitted = False
        try:
            async for event in transport.stream(request):
                emitted = True
                yield event
            return
        except (OpenAIError, httpx.HTTPError, ValueError) as exc:
            if emitted or not _is_retryable(exc) or attempt >= max_retries:
                raise AgentExecutionError("model transport failed") from exc
            attempt += 1
            await asyncio.sleep(retry_base_delay_seconds * (2 ** (attempt - 1)))


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_HTTP_STATUS_CODES
    if isinstance(exc, httpx.HTTPError):
        return True
    return isinstance(exc, _RETRYABLE_OPENAI_ERRORS)


__all__ = ["sample"]
