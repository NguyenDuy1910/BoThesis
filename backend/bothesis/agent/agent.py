from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import uuid4

from openai import PermissionDeniedError

from bothesis.agent import (
    AgentStreamEvent,
    AgentExecutionError,
    ContextManager,
    ResolvedStepSettings,
    Session,
    SessionConfiguration,
    SessionServices,
    ResourceResolver,
    TextInput,
    TurnContext,
    TurnEnvironmentSnapshot,
    UserTurn,
)
from bothesis.agent.models import AgentContext
from bothesis.agent.protocol import (
    Response,
    ResponseError,
    ResponseFailedEvent,
)
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.turn import run_turn
from bothesis.observability import NoopTracer, TraceSerializer, Tracer

_log = logging.getLogger(__name__)


class Agent:
    """Public agent runtime with one streaming execution path."""

    def __init__(
        self,
        model: object,
        tools: ToolRegistry,
        *,
        configuration: SessionConfiguration | None = None,
        tracer: Tracer | None = None,
        resource_resolver: ResourceResolver | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self.configuration = configuration or SessionConfiguration()
        self._tracer = tracer or NoopTracer()
        self._resource_resolver = resource_resolver

    @property
    def model(self) -> object:
        """The configured model transport; retained as a read-only diagnostic."""

        return self._model

    @property
    def tools(self) -> ToolRegistry:
        """Registered executors; per-step visibility is resolved by ToolRouter."""

        return self._tools

    def _session(self, resource_resolver: ResourceResolver | None) -> Session:
        return Session(
            self.configuration,
            SessionServices(
                model=self._model,
                tool_registry=self._tools,
                resource_resolver=resource_resolver,
                tracer=self._tracer,
            ),
            ContextManager(configuration=self.configuration),
        )

    async def run(
        self,
        user_turn: UserTurn | str,
        ctx: AgentContext,
        *,
        resource_resolver: ResourceResolver | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
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

        turn_input = _coerce_user_turn(user_turn)
        rejection = _rejection(turn_input, ctx, self.configuration)
        if rejection is not None:
            sequence_number += 1
            yield failure("invalid_request", rejection)
            return

        session = self._session(resource_resolver or self._resource_resolver)
        settings = ResolvedStepSettings(
            model=self.configuration.model,
            temperature=self.configuration.temperature,
            max_output_tokens=self.configuration.max_tokens,
            parallel_tool_calls=True,
            provider_options=dict(ctx.model_extra_body or {}),
        )
        turn = TurnContext(
            user_turn=turn_input,
            environment=TurnEnvironmentSnapshot(agent_context=ctx),
            initial_settings=settings,
            current_settings=settings,
            resources=_turn_resources(turn_input, ctx),
        )
        # Trace start: this parent span owns the complete agent-turn lifecycle.
        with self._tracer.span(
            "agent.turn",
            attributes=TraceSerializer.turn_attributes(ctx, turn_id=turn.id),
            input=TraceSerializer.full(
                TraceSerializer.turn_input(
                    user_input=turn_input.text,
                    model=self.configuration.model,
                    provider=getattr(self._model, "provider", None),
                    resources=(*turn_input.resources, *ctx.resources),
                    available_tools=tuple(
                        executor.as_function_tool()
                        for _, executor in self._tools.executors()
                    ),
                    available_tool_count=len(self._tools.executors()),
                )
            ),
        ) as trace:
            started_at = perf_counter()
            try:
                final_answer = ""
                async for event in run_turn(session, turn):
                    sequence_number += 1
                    if event.type == "response.completed":
                        final_answer = event.response.final_answer_text.strip() or final_answer
                    yield event.model_copy(
                        update={"sequence_number": sequence_number}
                    )
                trace.set_output(
                    TraceSerializer.full(
                        TraceSerializer.turn_output(
                            status="completed",
                            step_count=turn.model_iteration,
                            tool_call_count=turn.tool_call_count,
                            final_answer=final_answer,
                            sources_found=len(turn.evidence),
                            sources_used=len(turn.used_evidence_ids),
                            duration_ms=round((perf_counter() - started_at) * 1_000),
                            model_duration_ms=turn.model_duration_ms,
                            tool_duration_ms=turn.tool_duration_ms,
                        )
                    )
                )
            except AgentExecutionError as exc:
                _log.error("agent execution failed: %s", exc, exc_info=True)
                trace.set_output(
                    TraceSerializer.full(
                        TraceSerializer.turn_output(
                            status="failed",
                            step_count=turn.model_iteration,
                            tool_call_count=turn.tool_call_count,
                            duration_ms=round((perf_counter() - started_at) * 1_000),
                            model_duration_ms=turn.model_duration_ms,
                            tool_duration_ms=turn.tool_duration_ms,
                        )
                    )
                )
                sequence_number += 1
                yield failure(*_failure_reason(exc))
            # Trace end: final status and timing are recorded before the span closes.

def _rejection(
    turn: UserTurn, ctx: AgentContext, config: SessionConfiguration
) -> str | None:
    """Return why a request cannot be accepted, or ``None`` when it can."""

    if not turn.text and not turn.resources:
        return "message must not be empty"
    if len(turn.text) > config.max_user_message_characters:
        return "message exceeds the allowed length"
    if not ctx.tenant_id or not ctx.user_id:
        return "tenant and user context are required"
    return None


def _coerce_user_turn(value: UserTurn | str) -> UserTurn:
    """Keep the string API usable while all runtime state uses UserTurn."""

    if isinstance(value, UserTurn):
        return value
    return UserTurn(inputs=(TextInput(text=value),))


def _turn_resources(turn: UserTurn, context: AgentContext):
    """Capture the stable, access-checked resource surface for this turn."""

    resources = list(turn.resources)
    seen = {resource.id for resource in resources}
    for resource in context.resources:
        if resource.id not in seen:
            seen.add(resource.id)
            resources.append(resource)
    return tuple(resources)


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
