from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import nullcontext
from uuid import uuid4

from openai import PermissionDeniedError

from bothesis.agent import (
    AgentExecutionError,
    ContextManager,
    ResolvedStepSettings,
    Session,
    SessionConfiguration,
    SessionServices,
    TurnContext,
    TurnEnvironmentSnapshot,
)
from bothesis.agent.models import AgentContext
from bothesis.agent.protocol import (
    Response,
    ResponseError,
    ResponseFailedEvent,
    ResponseStreamEvent,
)
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.turn import run_turn
from bothesis.observability import LangfuseTracing

_log = logging.getLogger(__name__)


class Agent:
    """Public agent runtime with one streaming execution path."""

    def __init__(
        self,
        model: object,
        tools: ToolRegistry,
        *,
        configuration: SessionConfiguration | None = None,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self.configuration = configuration or SessionConfiguration()
        self._tracing = tracing

    @property
    def model(self) -> object:
        """The configured model transport; retained as a read-only diagnostic."""

        return self._model

    @property
    def tools(self) -> ToolRegistry:
        """Registered executors; per-step visibility is resolved by ToolRouter."""

        return self._tools

    async def run(
        self,
        user_message: str,
        ctx: AgentContext,
    ) -> AsyncIterator[ResponseStreamEvent]:
        """Yield ordered response state mutations for one conversation turn.

        A new in-memory Session is created for this conversation request. Its
        canonical context is never built from the presentation event stream.
        """

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
        rejection = _rejection(normalized_message, ctx, self.configuration)
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
                session = self._session()
                settings = ResolvedStepSettings(
                    model=self.configuration.model,
                    temperature=self.configuration.temperature,
                    max_output_tokens=self.configuration.max_tokens,
                    parallel_tool_calls=True,
                    provider_options=dict(ctx.model_extra_body or {}),
                )
                turn = TurnContext(
                    user_input=normalized_message,
                    environment=TurnEnvironmentSnapshot(agent_context=ctx),
                    initial_settings=settings,
                    current_settings=settings,
                )
                final_answer = ""
                async for event in run_turn(session, turn):
                    sequence_number += 1
                    if event.type == "response.completed":
                        final_answer = event.response.final_answer_text.strip() or final_answer
                    yield event.model_copy(
                        update={"sequence_number": sequence_number}
                    )
                if run_trace is not None and final_answer:
                    run_trace.complete(
                        answer=final_answer,
                        answer_characters=len(final_answer),
                        turn_count=turn.model_iteration,
                        tool_call_count=turn.tool_call_count,
                        sources_found=len(turn.evidence),
                        sources_used=len(turn.used_evidence_ids),
                    )
            except AgentExecutionError as exc:
                _log.error("agent execution failed: %s", exc, exc_info=True)
                if run_trace is not None:
                    run_trace.fail(stage="model")
                sequence_number += 1
                yield failure(*_failure_reason(exc))
    def _session(self) -> Session:
        return Session(
            self.configuration,
            SessionServices(
                model=self._model, tool_registry=self._tools, tracing=self._tracing
            ),
            ContextManager(configuration=self.configuration),
        )


def _rejection(
    message: str, ctx: AgentContext, config: SessionConfiguration
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
