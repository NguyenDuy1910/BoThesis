"""Controlled execution lifecycle for calls produced by one StepContext."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from time import perf_counter
from typing import TYPE_CHECKING, Any

from bothesis.agent import ResourceRef, duration_ms
from bothesis.agent.models import ToolObservation, ToolResult
from bothesis.agent.protocol import FunctionCallOutputItem, ToolCall
from bothesis.agent.tools import (
    ToolCallSource,
    ToolExecutionBatch,
    ToolInvocation,
    ToolPayload,
    ToolProgressReporter,
)
from bothesis.observability import NoopTracer, TraceSerializer, Tracer

if TYPE_CHECKING:
    from bothesis.agent import Session, StepContext, TurnContext
    from bothesis.agent.tools.core.router import ToolRouter

_UNEXECUTED_OUTCOMES = frozenset(
    {"duplicate_call", "invalid_arguments", "tool_call_limit", "tool_not_exposed", "unknown_tool"}
)


class ToolOrchestrator:
    """Validate, execute and normalize calls without owning turn control flow."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_output_characters: int,
        tracer: Tracer | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_output_characters = max_output_characters
        self._tracer = tracer or NoopTracer()

    async def execute(
        self,
        calls: Sequence[ToolCall],
        *,
        session: "Session",
        turn: "TurnContext",
        step_context: "StepContext",
        tool_router: "ToolRouter",
        resources: tuple[ResourceRef, ...],
        remaining_calls: int,
        on_progress: ToolProgressReporter | None = None,
    ) -> ToolExecutionBatch:
        """Execute calls only when their originating runtime router exposed them."""

        observations: list[ToolObservation | None] = [None] * len(calls)
        pending: list[tuple[int, ToolCall, ToolInvocation, Any]] = []
        for index, call in enumerate(calls):
            arguments = _decoded_arguments(call)
            if arguments is None:
                observations[index] = _error_observation(call, "Invalid arguments for tool.", "invalid_arguments")
                continue
            if not tool_router.is_exposed(call.name):
                observations[index] = _error_observation(call, "Tool is not exposed for this sampling step.", "tool_not_exposed")
                continue
            executor = tool_router.registry.get(call.name)
            if executor is None:
                observations[index] = _error_observation(call, f"Unknown tool: {call.name}", "unknown_tool")
                continue
            if not tool_router.registry.arguments_are_valid(call.name, arguments):
                observations[index] = _error_observation(call, f"Invalid arguments for tool: {call.name}", "invalid_arguments")
                continue
            signature = _tool_signature(call.name, arguments)
            if signature in turn.executed_tool_signatures:
                observations[index] = _error_observation(call, "This exact tool request was already executed in this run.", "duplicate_call")
                continue
            if len(pending) >= remaining_calls:
                observations[index] = _error_observation(call, "The tool-call limit was reached for this run.", "tool_call_limit")
                continue
            turn.executed_tool_signatures.add(signature)
            pending.append((index, call, ToolInvocation(
                session=session,
                turn=turn,
                step_context=step_context,
                call_id=call.call_id,
                tool_name=call.name,
                source=ToolCallSource.MODEL,
                payload=ToolPayload(arguments=arguments),
                resources=resources,
                progress_reporter=on_progress,
            ), executor))

        tasks = [
            asyncio.create_task(self._execute_one(index, call, invocation, executor))
            for index, call, invocation, executor in pending
        ]
        try:
            for task in asyncio.as_completed(tasks):
                index, observation = await task
                observations[index] = observation
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

        completed = tuple(item for item in observations if item is not None)
        for observation in completed:
            for source in observation.output.evidence:
                existing = turn.evidence.get(source.id)
                if existing is None or (
                    source.relevance_score is not None
                    and (existing.relevance_score is None or source.relevance_score > existing.relevance_score)
                ):
                    turn.evidence[source.id] = source
            # Trace start: bind each completed tool result to its next-step observation.
            with self._tracer.span(
                "observation",
                attributes={
                    "tool_name": observation.call.name,
                    "tool_call_id": observation.call.call_id,
                },
                input=TraceSerializer.full(
                    TraceSerializer.observation(
                        call=observation.call,
                        result=observation.result,
                        included_in_next_step=True,
                    )
                ),
            ) as trace:
                trace.set_output(
                    TraceSerializer.full(
                        {
                            "status": observation.status,
                            "duration_ms": observation.duration_ms,
                            "included_in_next_step": True,
                        }
                    )
                )
            # Trace end: this observation is ready for the next context.build span.
        return ToolExecutionBatch(
            output_items=tuple(_output_item(item, self._max_output_characters) for item in completed),
            model_content=tuple(
                content
                for observation in completed
                for content in observation.result.model_content
            ),
            duration_ms=sum(item.duration_ms for item in completed),
            executed_call_count=sum(item.output.metadata.get("outcome") not in _UNEXECUTED_OUTCOMES for item in completed),
        )

    async def _execute_one(
        self, index: int, call: ToolCall, invocation: ToolInvocation, executor: Any
    ) -> tuple[int, ToolObservation]:
        started_at = perf_counter()
        await invocation.report_progress("started", {})
        # Trace start: capture the exact model-requested tool call and arguments.
        with self._tracer.span(
            f"tool.execute: {call.name}",
            attributes={"tool_name": call.name, "tool_call_id": call.call_id},
            input=TraceSerializer.full(
                TraceSerializer.tool_input(
                    tool_name=call.name, arguments=invocation.payload.arguments
                )
            ),
        ) as trace:
            try:
                output = await asyncio.wait_for(
                    executor.handle(invocation), timeout=self._budget_for(executor)
                )
            except TimeoutError:
                output = ToolResult(content="", error="Tool execution timed out.", metadata={"outcome": "timeout", "result_count": 0})
            except Exception:  # noqa: BLE001 - tools expose only safe failures
                output = ToolResult(content="", error="Tool execution failed.", metadata={"outcome": "failed", "result_count": 0})
            trace.set_output(TraceSerializer.full(TraceSerializer.tool_output(output)))
            # Trace end: the safe structured tool result is attached before closing.
        observation = ToolObservation(
            call=call,
            result=output,
            duration_ms=duration_ms(started_at),
        )
        await invocation.report_progress(
            "completed",
            {
                "status": observation.status,
                "result_count": observation.result_count,
                "duration_ms": observation.duration_ms,
            },
        )
        return index, observation


    def _budget_for(self, executor: Any) -> float:
        """The wall-clock budget for one call, honouring a tool's own declaration."""

        declared = getattr(executor.spec(), "timeout_seconds", None)
        return declared if declared is not None else self._timeout_seconds


def _decoded_arguments(call: ToolCall) -> dict[str, Any] | None:
    try:
        return call.parsed_arguments()
    except ValueError:
        return None


def _tool_signature(name: str, arguments: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"


def _error_observation(call: ToolCall, error: str, outcome: str) -> ToolObservation:
    return ToolObservation(call=call, result=ToolResult(content="", error=error, metadata={"outcome": outcome, "result_count": 0}), duration_ms=0)


def _output_item(observation: ToolObservation, max_characters: int) -> FunctionCallOutputItem:
    content = f"Tool error: {observation.output.error}" if observation.output.error else observation.output.content or "Tool completed without a textual result."
    if len(content) > max_characters:
        content = f"{content[: max(1, max_characters - 1)].rstrip()}…"
    return FunctionCallOutputItem(id=f"tool-output:{observation.call.call_id}", call_id=observation.call.call_id, output=content, status="completed")


__all__ = ["ToolOrchestrator"]
