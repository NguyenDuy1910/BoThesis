"""The conversation-level entry point for the BoThesis agent runtime.

One user request is one Turn Request
(:class:`~bothesis.agent.turn_request.TurnRequest`), which itself loops
through as many Sampling Requests as it takes to reach a final answer.
``ConversationSession`` holds the dependencies shared across requests (model,
tools, memory, tracing) and constructs one fresh ``TurnRequest`` per call —
it does not run the loop itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from bothesis.agent import AgentConfig
from bothesis.agent.conversation_compression import ConversationMemory
from bothesis.agent.models import AgentContext
from bothesis.agent.protocol import ResponseStreamEvent
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.transports.openai import OpenAITransport
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.agent.turn_request import TurnRequest
from bothesis.observability import AgentRunTrace, LangfuseTracing


class ConversationSession:
    """Construct one fresh :class:`TurnRequest` per user message."""

    def __init__(
        self,
        model: OpenAITransport | OpenRouterTransport,
        tools: ToolRegistry,
        *,
        memory: ConversationMemory,
        config: AgentConfig,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        provider = getattr(model, "provider", None)
        if provider not in {"openai", "openrouter"}:
            raise ValueError("model must be an OpenAI or OpenRouter transport")
        self._model = model
        self._provider = provider
        self._tools = tools
        self._memory = memory
        self._config = config
        self._tracing = tracing

    async def run_session(
        self,
        user_message: str,
        ctx: AgentContext,
        *,
        run_trace: AgentRunTrace | None,
    ) -> AsyncIterator[ResponseStreamEvent]:
        """Execute one user request as a fresh Turn Request."""

        turn_request = TurnRequest(
            self._model,
            self._provider,
            self._tools,
            memory=self._memory,
            config=self._config,
            tracing=self._tracing,
        )
        async for event in turn_request.run_turn(user_message, ctx, run_trace=run_trace):
            yield event

__all__ = ["ConversationSession"]
