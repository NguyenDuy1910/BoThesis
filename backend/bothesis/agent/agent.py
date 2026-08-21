"""Thin public façade for the BoThesis agent runtime."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import nullcontext
from uuid import uuid4

from openai import PermissionDeniedError

from bothesis.agent import AgentConfig, AgentExecutionError
from bothesis.agent.conversation_compression import ConversationMemory
from bothesis.agent.conversation_session import ConversationSession
from bothesis.agent.models import AgentContext
from bothesis.agent.protocol import Response, ResponseError, ResponseFailedEvent, ResponseStreamEvent
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.transports.openai import OpenAITransport
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.observability import LangfuseTracing

_log = logging.getLogger(__name__)


class Agent:
    """Public agent runtime with one streaming execution path."""

    def __init__(
        self,
        model: OpenAITransport | OpenRouterTransport,
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
        self._conversation_session = ConversationSession(
            model,
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
        """Yield ordered response state mutations for one conversation Turn."""

        sequence_number = 0

        def failure(message: str) -> ResponseFailedEvent:
            return ResponseFailedEvent(
                sequence_number=sequence_number + 1,
                response=Response(
                    id=f"resp_{uuid4().hex}",
                    status="failed",
                    error=ResponseError(code="invalid_request", message=message),
                ),
            )

        normalized_message = user_message.strip()
        if not normalized_message:
            yield failure("message must not be empty")
            return
        if len(normalized_message) > self.config.max_user_message_characters:
            yield failure("message exceeds the allowed length")
            return
        if not ctx.tenant_id or not ctx.user_id:
            yield failure("tenant and user context are required")
            return

        trace_context = (
            self._tracing.agent_run(user_message=normalized_message, ctx=ctx)
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as run_trace:
            try:
                async for event in self._conversation_session.run_session(
                    normalized_message,
                    ctx,
                    run_trace=run_trace,
                ):
                    sequence_number += 1
                    yield event.model_copy(update={"sequence_number": sequence_number})
            except AgentExecutionError as exc:
                _log.error(
                    "agent execution failed: %s",
                    exc,
                    exc_info=True,
                )
                if run_trace is not None:
                    run_trace.fail(stage="model")
                error_code = "agent_execution_failed"
                error_message = "model response failed"
                if isinstance(exc.__cause__, PermissionDeniedError):
                    error_code = "model_access_denied"
                    error_message = (
                        "OpenAI denied the request. Verify that the configured "
                        "model is enabled for this API project."
                    )
                sequence_number += 1
                yield ResponseFailedEvent(
                    sequence_number=sequence_number,
                    response=Response(
                        id=f"resp_{uuid4().hex}",
                        status="failed",
                        error=ResponseError(
                            code=error_code,
                            message=error_message,
                        ),
                    ),
                )


__all__ = ["Agent"]
