"""Retry one logical sampling request across transient transport failures.

A retry repeats the exact same model sampling because the transport failed
transiently (a dropped connection, a rate limit, a 5xx). It is not a turn
continuation: continuing to a new sampling because tool results now exist is
the Turn Loop's job (:class:`~bothesis.agent.conversation_loop.ConversationLoop`),
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

from bothesis.agent import AgentExecutionError, ModelStreamCompleted
from bothesis.agent.models import AgentEvent
from bothesis.agent.protocol import ResponseRequest
from bothesis.agent.response_stream import (
    ResponseStreamProcessor,
    openai_canonical_events,
    openrouter_canonical_events,
)
from bothesis.agent.step_context import StepContext

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
        model=step.model,
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
    *,
    generation_trace: Any = None,
) -> AsyncIterator[AgentEvent | ModelStreamCompleted]:
    """Attempt one sampling request, retrying transient transport failures."""

    prompt = _build_prompt(step)
    attempt = 0
    while True:
        try:
            processor = ResponseStreamProcessor(
                turn_number=step.turn_number,
                generation_trace=generation_trace,
            )
            events = (
                openai_canonical_events(step.transport, prompt)
                if step.provider == "openai"
                else openrouter_canonical_events(step.transport, prompt)
            )
            async for event in processor.run(events):
                yield event
            return
        except (OpenAIError, httpx.HTTPError, ValueError) as exc:
            if not _is_retryable(exc) or attempt >= step.config.max_sampling_retries:
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
