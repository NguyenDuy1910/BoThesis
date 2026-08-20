"""Retry one logical sampling request across transient transport failures.

A retry repeats the exact same model sampling because the transport failed
transiently (a dropped connection, a rate limit, a 5xx). It is not a turn
continuation: continuing to a new sampling because tool results now exist is
the Turn Loop's job (:class:`~bothesis.agent.conversation_session.ConversationSession`),
not this module's.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAIError,
    RateLimitError,
)

from bothesis.agent import AgentExecutionError, ModelStreamCompleted, TextDelta
from bothesis.agent.protocol import ReasoningSummaryDelta, ResponseRequest
from bothesis.agent.response_stream import (
    StreamResponse,
    openai_canonical_events,
    openrouter_canonical_events,
)
from bothesis.agent.step_context import StepContext
from bothesis.agent.transports.openai import OpenAITransport
from bothesis.agent.transports.openrouter import OpenRouterTransport

_RETRYABLE_OPENAI_ERRORS: tuple[type[Exception], ...] = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
_RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _build_prompt(step: StepContext) -> ResponseRequest:
    """Assemble the one provider-neutral request for this sampling attempt.

    Built once from a stable :class:`StepContext` so a provider retry
    replays the exact same request instead of a freshly re-derived one.
    """

    return ResponseRequest(
        input=step.history.items,
        model=step.model_info.name,
        instructions=step.history.instructions,
        tools=step.tools,
        tool_choice="auto" if step.tools else None,
        parallel_tool_calls=True if step.tools else None,
        temperature=step.config.temperature,
        max_output_tokens=step.config.max_tokens,
        provider_options=dict(step.agent_context.model_extra_body or {}),
    )


async def run_sampling_request(
    step: StepContext,
    transport: OpenAITransport | OpenRouterTransport,
    *,
    generation_trace: Any = None,
) -> AsyncIterator[TextDelta | ReasoningSummaryDelta | ModelStreamCompleted]:
    """Attempt one sampling request, retrying transient transport failures."""

    prompt = _build_prompt(step)
    attempt = 0
    while True:
        emitted_text = False
        try:
            response_stream = StreamResponse(
                provider=step.model_info.provider,
                sampling_number=step.turn_number,
                generation_trace=generation_trace,
            )
            events = (
                openai_canonical_events(transport, prompt)
                if step.model_info.provider == "openai"
                else openrouter_canonical_events(transport, prompt)
            )
            async for event in response_stream.run_llm(events):
                if isinstance(event, TextDelta):
                    emitted_text = True
                yield event
            return
        except (OpenAIError, httpx.HTTPError, ValueError) as exc:
            if (
                emitted_text
                or not _is_retryable(exc)
                or attempt >= step.config.max_sampling_retries
            ):
                raise AgentExecutionError("model transport failed") from exc
            attempt += 1
            await asyncio.sleep(step.config.sampling_retry_base_delay_seconds * (2 ** (attempt - 1)))


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_HTTP_STATUS_CODES
    if isinstance(exc, httpx.HTTPError):
        return True
    return isinstance(exc, _RETRYABLE_OPENAI_ERRORS)


__all__ = ["run_sampling_request"]
