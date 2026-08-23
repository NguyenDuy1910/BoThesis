"""Execute one response's function calls and return canonical observations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from time import perf_counter
from typing import Any

from bothesis.agent.models import Evidence, ToolContext, ToolObservation, ToolOutput
from bothesis.agent.protocol import FunctionCallItem, FunctionCallOutputItem
from bothesis.agent.tools import ToolExecutionBatch
from bothesis.agent.tools.registry import ToolRegistry
from bothesis.observability import LangfuseTracing


_UNEXECUTED_OUTCOMES = frozenset(
    {
        "duplicate_call",
        "invalid_arguments",
        "tool_call_limit",
        "tool_not_allowed",
        "unknown_tool",
    }
)


class ToolExecutor:
    """Validate and run independent calls concurrently.

    Tool timing and outcomes remain runtime telemetry. The client observes the
    model's ``function_call`` output item; its corresponding
    ``function_call_output`` is accumulated only as immutable next-step input.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        timeout_seconds: float,
        max_output_characters: int,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds
        self._max_output_characters = max_output_characters
        self._tracing = tracing

    async def execute(
        self,
        calls: Sequence[FunctionCallItem],
        *,
        context: ToolContext,
        remaining_calls: int,
        previous_signatures: set[str],
        evidence: dict[str, Evidence],
        allowed_tool_names: Sequence[str] | None = None,
    ) -> ToolExecutionBatch:
        """Execute all safe independent calls and preserve model call order."""

        observations: list[ToolObservation | None] = [None] * len(calls)
        pending: list[tuple[int, FunctionCallItem, dict[str, Any]]] = []
        allowed = (
            frozenset(allowed_tool_names)
            if allowed_tool_names is not None
            else None
        )
        for index, call in enumerate(calls):
            arguments = _decoded_arguments(call)
            if arguments is None:
                observations[index] = _error_observation(
                    call, "Invalid arguments for tool.", "invalid_arguments"
                )
                continue
            tool = self._registry.get(call.name)
            if tool is None:
                observations[index] = _error_observation(
                    call, f"Unknown tool: {call.name}", "unknown_tool"
                )
                continue
            if allowed is not None and call.name not in allowed:
                observations[index] = _error_observation(
                    call,
                    "Tool is not available for this request.",
                    "tool_not_allowed",
                )
                continue
            if not self._registry.arguments_are_valid(call.name, arguments):
                observations[index] = _error_observation(
                    call, f"Invalid arguments for tool: {call.name}", "invalid_arguments"
                )
                continue
            signature = _tool_signature(call.name, arguments)
            if signature in previous_signatures:
                observations[index] = _error_observation(
                    call,
                    "This exact tool request was already executed in this run.",
                    "duplicate_call",
                )
                continue
            if len(pending) >= remaining_calls:
                observations[index] = _error_observation(
                    call,
                    "The tool-call limit was reached for this run.",
                    "tool_call_limit",
                )
                continue
            previous_signatures.add(signature)
            pending.append((index, call, arguments))

        tasks = [
            asyncio.create_task(self._execute_indexed(index, call, arguments, context))
            for index, call, arguments in pending
        ]
        try:
            for future in asyncio.as_completed(tasks):
                index, observation = await future
                observations[index] = observation
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

        completed = tuple(observation for observation in observations if observation is not None)
        for observation in completed:
            for source in observation.output.evidence:
                existing = evidence.get(source.id)
                if existing is None or (
                    source.relevance_score is not None
                    and (
                        existing.relevance_score is None
                        or source.relevance_score > existing.relevance_score
                    )
                ):
                    evidence[source.id] = source
        return ToolExecutionBatch(
            output_items=tuple(
                _output_item(observation, self._max_output_characters)
                for observation in completed
            ),
            duration_ms=sum(observation.duration_ms for observation in completed),
            executed_call_count=sum(
                observation.output.metadata.get("outcome") not in _UNEXECUTED_OUTCOMES
                for observation in completed
            ),
        )

    async def _execute_indexed(
        self,
        index: int,
        call: FunctionCallItem,
        arguments: Mapping[str, Any],
        context: ToolContext,
    ) -> tuple[int, ToolObservation]:
        return index, await self._execute_one(call, arguments, context)

    async def _execute_one(
        self,
        call: FunctionCallItem,
        arguments: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolObservation:
        tool = self._registry.get(call.name)
        if tool is None:
            return _error_observation(call, f"Unknown tool: {call.name}", "unknown_tool")
        started_at = perf_counter()
        trace_context = (
            self._tracing.tool_execution(name=call.name, arguments=arguments)
            if self._tracing is not None
            else nullcontext(None)
        )
        try:
            with trace_context as trace:
                output = await asyncio.wait_for(
                    tool.execute(dict(arguments), context), timeout=self._timeout_seconds
                )
                if trace is not None:
                    trace.complete(result=output)
        except TimeoutError:
            output = ToolOutput(
                content="", error="Tool execution timed out.",
                metadata={"outcome": "timeout", "result_count": 0},
            )
        except Exception:  # noqa: BLE001 - failure is an agent observation
            output = ToolOutput(
                content="", error="Tool execution failed.",
                metadata={"outcome": "failed", "result_count": 0},
            )
        return ToolObservation(
            call=call,
            output=output,
            duration_ms=round((perf_counter() - started_at) * 1_000),
        )


def _error_observation(call: FunctionCallItem, error: str, outcome: str) -> ToolObservation:
    return ToolObservation(
        call=call,
        output=ToolOutput(content="", error=error, metadata={"outcome": outcome, "result_count": 0}),
        duration_ms=0,
    )


def _decoded_arguments(call: FunctionCallItem) -> dict[str, Any] | None:
    try:
        return call.parsed_arguments()
    except ValueError:
        return None


def _tool_signature(name: str, arguments: Mapping[str, Any]) -> str:
    return f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"


def _output_item(observation: ToolObservation, max_characters: int) -> FunctionCallOutputItem:
    content = observation.output.content
    if observation.output.error:
        content = f"Tool error: {observation.output.error}"
    elif not content:
        content = "Tool completed without a textual result."
    if len(content) > max_characters:
        content = f"{content[: max(1, max_characters - 1)].rstrip()}…"
    # A developer-supplied output is always ``completed``: the specification
    # defines no failure status for an item, so a tool failure is reported in
    # ``output`` and the runtime outcome stays in telemetry.
    return FunctionCallOutputItem(
        id=f"tool-output:{observation.call.call_id}",
        call_id=observation.call.call_id,
        output=content,
        status="completed",
    )


__all__ = ["ToolExecutionBatch", "ToolExecutor"]
