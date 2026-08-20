"""Execute model-requested tools and project their runtime outcomes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import nullcontext
from time import perf_counter
from typing import Any

from bothesis.agent.models import Evidence, ToolContext, ToolObservation, ToolOutput
from bothesis.agent.protocol import (
    EvidenceItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    ItemCompleted,
    ItemStarted,
    RuntimeStreamEvent,
    ToolCallItem,
    ToolResultItem,
)
from bothesis.agent.tools import ToolExecutionBatch
from bothesis.agent.tools.registry import ToolRegistry
from bothesis.observability import LangfuseTracing


_UNEXECUTED_OUTCOMES = frozenset(
    {"invalid_arguments", "unknown_tool", "duplicate_call", "tool_call_limit"}
)


class ToolExecutor:
    """Own validation, execution, result projection, and item lifecycles."""

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
        sampling_number: int,
        evidence: dict[str, Evidence],
    ) -> AsyncIterator[RuntimeStreamEvent | ToolExecutionBatch]:
        """Run calls concurrently and emit their lifecycles at actual boundaries."""

        observations: list[ToolObservation | None] = [None] * len(calls)
        pending: list[tuple[int, FunctionCallItem, dict[str, Any]]] = []
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

        for call in calls:
            yield ItemStarted(item=self._call_item(call, sampling_number))
            yield ItemStarted(item=self._pending_result_item(call, sampling_number))

        for observation in observations:
            if observation is not None:
                for event in self._completion_events(
                    observation, sampling_number, evidence
                ):
                    yield event

        tasks = [
            asyncio.create_task(self._execute_indexed(index, call, arguments, context))
            for index, call, arguments in pending
        ]
        try:
            for future in asyncio.as_completed(tasks):
                index, observation = await future
                observations[index] = observation
                for event in self._completion_events(
                    observation, sampling_number, evidence
                ):
                    yield event
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

        completed_observations = tuple(
            observation for observation in observations if observation is not None
        )
        yield ToolExecutionBatch(
            output_items=tuple(
                _output_item(observation, self._max_output_characters)
                for observation in completed_observations
            ),
            duration_ms=sum(observation.duration_ms for observation in completed_observations),
            executed_call_count=sum(
                1
                for observation in completed_observations
                if observation.output.metadata.get("outcome") not in _UNEXECUTED_OUTCOMES
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
                    tool.execute(dict(arguments), context),
                    timeout=self._timeout_seconds,
                )
                if trace is not None:
                    trace.complete(result=output)
        except TimeoutError:
            output = ToolOutput(
                content="",
                error="Tool execution timed out.",
                metadata={"outcome": "timeout", "result_count": 0},
            )
        except Exception:  # noqa: BLE001 - failures are model observations
            output = ToolOutput(
                content="",
                error="Tool execution failed.",
                metadata={"outcome": "failed", "result_count": 0},
            )
        return ToolObservation(
            call=call,
            output=output,
            duration_ms=round((perf_counter() - started_at) * 1_000),
        )

    def _call_item(self, call: FunctionCallItem, sampling_number: int) -> ToolCallItem:
        label, category = self._activity_metadata(call.name)
        return ToolCallItem(
            id=_activity_id(sampling_number, call),
            call_id=call.call_id,
            name=call.name,
            label=label,
            category=category,
        )

    def _result_item(
        self, observation: ToolObservation, sampling_number: int
    ) -> ToolResultItem:
        return ToolResultItem(
            id=f"{_activity_id(sampling_number, observation.call)}:result",
            call_id=observation.call.call_id,
            name=observation.call.name,
            error=observation.output.error,
            duration_ms=observation.duration_ms,
            result_count=observation.result_count,
            status=observation.status,
        )

    @staticmethod
    def _pending_result_item(
        call: FunctionCallItem, sampling_number: int
    ) -> ToolResultItem:
        return ToolResultItem(
            id=f"{_activity_id(sampling_number, call)}:result",
            call_id=call.call_id,
            name=call.name,
            status="in_progress",
        )

    def _completion_events(
        self,
        observation: ToolObservation,
        sampling_number: int,
        evidence: dict[str, Evidence],
    ) -> tuple[RuntimeStreamEvent, ...]:
        events = self._evidence_events(observation.output.evidence, evidence)
        call_item = self._call_item(observation.call, sampling_number)
        call_status = (
            "completed"
            if observation.status == "completed"
            else "skipped"
            if observation.status == "skipped"
            else "failed"
        )
        events.extend(
            (
                ItemCompleted(item=self._result_item(observation, sampling_number)),
                ItemCompleted(item=call_item.model_copy(update={"status": call_status})),
            )
        )
        return tuple(events)

    @staticmethod
    def _evidence_events(
        discovered: Sequence[Evidence], evidence: dict[str, Evidence]
    ) -> list[RuntimeStreamEvent]:
        events: list[RuntimeStreamEvent] = []
        for item in discovered:
            existing = evidence.get(item.id)
            if existing is None:
                evidence[item.id] = item
                reference = _evidence_item(item)
                events.extend((ItemStarted(item=reference), ItemCompleted(item=reference)))
            elif (
                item.relevance_score is not None
                and (existing.relevance_score is None or item.relevance_score > existing.relevance_score)
            ):
                evidence[item.id] = item
        return events

    def _activity_metadata(self, name: str) -> tuple[str, str]:
        tool = self._registry.get(name)
        if tool is None:
            return name.replace("_", " ").replace("-", " ").strip().title() or "Run tool", "tool"
        definition = tool.definition
        return definition.activity_label or definition.name.replace("_", " ").title(), definition.activity_category


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


def _activity_id(sampling_number: int, call: FunctionCallItem) -> str:
    return f"sampling-{sampling_number}-call-{call.call_id}"


def _output_item(observation: ToolObservation, max_characters: int) -> FunctionCallOutputItem:
    content = observation.output.content
    if observation.output.error:
        content = f"Tool error: {observation.output.error}"
    elif not content:
        content = "Tool completed without a textual result."
    if len(content) > max_characters:
        content = f"{content[: max(1, max_characters - 1)].rstrip()}…"
    return FunctionCallOutputItem(call_id=observation.call.call_id, output=content)


def _evidence_item(evidence: Evidence) -> EvidenceItem:
    from bothesis.agent import evidence_reference

    return evidence_reference(evidence)


__all__ = ["ToolExecutionBatch", "ToolExecutor"]
