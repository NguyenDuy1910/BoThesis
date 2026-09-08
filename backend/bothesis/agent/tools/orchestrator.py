"""Controlled execution lifecycle for calls produced by one StepContext."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from contextlib import nullcontext
from time import perf_counter
from typing import Any

from bothesis.agent import duration_ms
from bothesis.agent.models import Evidence, ToolObservation, ToolOutput
from bothesis.agent.protocol import FunctionCallItem, FunctionCallOutputItem
from bothesis.agent.tools import (
    ToolCallSource,
    ToolExecutionBatch,
    ToolInvocation,
    ToolPayload,
)
from bothesis.observability import LangfuseTracing

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
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_output_characters = max_output_characters
        self._tracing = tracing

    async def execute(
        self,
        calls: Sequence[FunctionCallItem],
        *,
        session: Any,
        step_context: Any,
        remaining_calls: int,
    ) -> ToolExecutionBatch:
        """Execute calls only when their originating router exposed them."""

        turn = step_context.turn
        observations: list[ToolObservation | None] = [None] * len(calls)
        pending: list[tuple[int, FunctionCallItem, ToolInvocation]] = []
        for index, call in enumerate(calls):
            arguments = _decoded_arguments(call)
            if arguments is None:
                observations[index] = _error_observation(call, "Invalid arguments for tool.", "invalid_arguments")
                continue
            if not step_context.tool_router.is_exposed(call.name):
                observations[index] = _error_observation(call, "Tool is not exposed for this sampling step.", "tool_not_exposed")
                continue
            executor = step_context.tool_router.registry.get(call.name)
            if executor is None:
                observations[index] = _error_observation(call, f"Unknown tool: {call.name}", "unknown_tool")
                continue
            if not step_context.tool_router.registry.arguments_are_valid(call.name, arguments):
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
            )))

        tasks = [asyncio.create_task(self._execute_one(index, call, invocation)) for index, call, invocation in pending]
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
        return ToolExecutionBatch(
            output_items=tuple(_output_item(item, self._max_output_characters) for item in completed),
            duration_ms=sum(item.duration_ms for item in completed),
            executed_call_count=sum(item.output.metadata.get("outcome") not in _UNEXECUTED_OUTCOMES for item in completed),
        )

    async def _execute_one(self, index: int, call: FunctionCallItem, invocation: ToolInvocation) -> tuple[int, ToolObservation]:
        executor = invocation.step_context.tool_router.registry.get(call.name)
        if executor is None:
            return index, _error_observation(call, f"Unknown tool: {call.name}", "unknown_tool")
        started_at = perf_counter()
        trace_context = self._tracing.tool_execution(name=call.name, arguments=invocation.payload.arguments) if self._tracing else nullcontext(None)
        try:
            with trace_context as trace:
                output = await asyncio.wait_for(executor.handle(invocation), timeout=self._timeout_seconds)
                if trace is not None:
                    trace.complete(result=output)
        except TimeoutError:
            output = ToolOutput(content="", error="Tool execution timed out.", metadata={"outcome": "timeout", "result_count": 0})
        except Exception:  # noqa: BLE001
            output = ToolOutput(content="", error="Tool execution failed.", metadata={"outcome": "failed", "result_count": 0})
        return index, ToolObservation(call=call, output=output, duration_ms=duration_ms(started_at))


def _decoded_arguments(call: FunctionCallItem) -> dict[str, Any] | None:
    try:
        return call.parsed_arguments()
    except ValueError:
        return None


def _tool_signature(name: str, arguments: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"


def _error_observation(call: FunctionCallItem, error: str, outcome: str) -> ToolObservation:
    return ToolObservation(call=call, output=ToolOutput(content="", error=error, metadata={"outcome": outcome, "result_count": 0}), duration_ms=0)


def _output_item(observation: ToolObservation, max_characters: int) -> FunctionCallOutputItem:
    content = f"Tool error: {observation.output.error}" if observation.output.error else observation.output.content or "Tool completed without a textual result."
    if len(content) > max_characters:
        content = f"{content[: max(1, max_characters - 1)].rstrip()}…"
    return FunctionCallOutputItem(id=f"tool-output:{observation.call.call_id}", call_id=observation.call.call_id, output=content, status="completed")


__all__ = ["ToolOrchestrator"]
