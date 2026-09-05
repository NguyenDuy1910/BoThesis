from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import nullcontext
from uuid import uuid4

from openai import PermissionDeniedError

from bothesis.agent import AgentConfig, AgentExecutionError
from bothesis.agent.conversation_compression import ConversationMemory
from bothesis.agent.conversation_loop import ConversationLoop
from bothesis.agent.models import AgentContext
from bothesis.agent.protocol import (
    Response,
    ResponseError,
    ResponseFailedEvent,
    ResponseStreamEvent,
)
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.transports import response_stream
from bothesis.observability import LangfuseTracing

_log = logging.getLogger(__name__)


class Agent:
    """Public agent runtime with one streaming execution path."""

    def __init__(
        self,
        model: object,
        tools: ToolRegistry,
        *,
        config: AgentConfig | None = None,
        memory: ConversationMemory | None = None,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.config = config or AgentConfig()
        self.memory = memory or ConversationMemory(config=self.config)
        self._tracing = tracing
        self._conversation_loop = ConversationLoop(
            response_stream(model),
            tools,
            memory=self.memory,
            config=self.config,
            tracing=tracing,
        )

    async def run(
        self,
        user_message: str,
        ctx: AgentContext,
    ) -> AsyncIterator[ResponseStreamEvent]:
        """Yield ordered response state mutations for one conversation turn."""

        sequence_number = 0

        def failure(code: str, message: str) -> ResponseFailedEvent:
            return ResponseFailedEvent(
                sequence_number=sequence_number,
                response=Response(
                    id=f"resp_{uuid4().hex}",
                    status="failed",
                    error=ResponseError(code=code, message=message),
                ),
            )

        normalized_message = user_message.strip()
        rejection = _rejection(normalized_message, ctx, self.config)
        if rejection is not None:
            sequence_number += 1
            yield failure("invalid_request", rejection)
            return

        trace_context = (
            self._tracing.agent_run(user_message=normalized_message, ctx=ctx)
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as run_trace:
            try:
                async for event in self._conversation_loop.run(
                    normalized_message,
                    ctx,
                    run_trace=run_trace,
                ):
                    sequence_number += 1
                    yield event.model_copy(
                        update={"sequence_number": sequence_number}
                    )
            except AgentExecutionError as exc:
                _log.error("agent execution failed: %s", exc, exc_info=True)
                if run_trace is not None:
                    run_trace.fail(stage="model")
                sequence_number += 1
                yield failure(*_failure_reason(exc))


def _rejection(
    message: str, ctx: AgentContext, config: AgentConfig
) -> str | None:
    """Return why a request cannot be accepted, or ``None`` when it can."""

    if not message:
        return "message must not be empty"
    if len(message) > config.max_user_message_characters:
        return "message exceeds the allowed length"
    if not ctx.tenant_id or not ctx.user_id:
        return "tenant and user context are required"
    return None


def _failure_reason(exc: AgentExecutionError) -> tuple[str, str]:
    """Turn an internal failure into a safe, actionable client error."""

    if isinstance(exc.__cause__, PermissionDeniedError):
        return (
            "model_access_denied",
            "OpenAI denied the request. Verify that the configured model is "
            "enabled for this API project.",
        )
    return "agent_execution_failed", "model response failed"


__all__ = ["Agent"]
