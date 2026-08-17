"""Thin public façade for the BoThesis agent runtime."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import nullcontext

from bothesis.agent import AgentConfig, AgentExecutionError
from bothesis.agent.conversation_compression import ConversationMemory
from bothesis.agent.conversation_loop import ConversationLoop
from bothesis.agent.models import (
    AgentContext,
    AgentEvent,
    RunFailed,
)
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
        self._conversation_loop = ConversationLoop(
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
    ) -> AsyncIterator[AgentEvent]:
        """Yield application events for one conversation run."""

        normalized_message = user_message.strip()
        if not normalized_message:
            yield RunFailed(error="message must not be empty")
            return
        if len(normalized_message) > self.config.max_user_message_characters:
            yield RunFailed(error="message exceeds the allowed length")
            return
        if not ctx.tenant_id or not ctx.user_id:
            yield RunFailed(error="tenant and user context are required")
            return

        trace_context = (
            self._tracing.agent_run(user_message=normalized_message, ctx=ctx)
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as run_trace:
            try:
                async for event in self._conversation_loop.stream(
                    normalized_message,
                    ctx,
                    run_trace=run_trace,
                ):
                    yield event
            except AgentExecutionError as exc:
                _log.error(
                    "agent execution failed: %s",
                    exc,
                    exc_info=True,
                )
                if run_trace is not None:
                    run_trace.fail(stage="model")
                yield RunFailed(error="model response failed")


__all__ = ["Agent"]
