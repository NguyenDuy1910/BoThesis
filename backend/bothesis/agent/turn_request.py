"""One user request executed end to end: the Turn Loop.

A Turn Request represents the full execution of one user request. It is not
one LLM call — it loops through as many Sampling Requests
(:func:`~bothesis.agent.sampling_request.run_sampling_request`, which owns the
provider retry loop and the canonical response-stream processing) as it takes
to alternate model decisions and tool observations into a final answer.
:class:`~bothesis.agent.conversation_loop.ConversationLoop` constructs one
fresh ``TurnRequest`` per user message and delegates entirely to it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import replace
from time import perf_counter
from typing import Any

from bothesis.agent import (
    AgentConfig,
    AgentExecutionError,
    ModelStreamCompleted,
    duration_ms,
    evidence_reference,
)
from bothesis.agent.citation import CitationRenderer
from bothesis.agent.conversation_compression import ConversationMemory
from bothesis.agent.models import (
    AgentContext,
    AgentEvent,
    CitationAvailable,
    CommentaryDelta,
    ConversationDocument,
    ConversationRun,
    FinalAnswerDelta,
    RunCompleted,
    ToolCompleted,
    ToolContext,
    ToolObservation,
    ToolOutput,
    ToolStarted,
)
from bothesis.agent.protocol import FunctionCallItem
from bothesis.agent.sampling_request import run_sampling_request
from bothesis.agent.step_context import Provider, StepContext, capture_step_context
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.transports.openai import OpenAITransport
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.agent.turn_input import ResponseItem
from bothesis.observability import AgentRunTrace, LangfuseTracing


class TurnRequest:
    """Alternate model decisions and tool observations until a final answer."""

    def __init__(
        self,
        model: OpenAITransport | OpenRouterTransport,
        provider: Provider,
        tools: ToolRegistry,
        *,
        memory: ConversationMemory,
        config: AgentConfig,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self._model = model
        self._provider = provider
        self._tools = tools
        self._memory = memory
        self._config = config
        self._tracing = tracing
        self._citations = CitationRenderer()

    async def run(
        self,
        user_message: str,
        ctx: AgentContext,
        *,
        run_trace: AgentRunTrace | None,
    ) -> AsyncIterator[AgentEvent]:
        """Run Think → Act → Observe dynamically using native tool calls."""

        started_at = perf_counter()
        state = ConversationRun(user_message=user_message)
        for event in self._register_document_evidence(ctx.documents, state):
            yield event

        turn_input = await self._memory.prepare(user_message, ctx)

        for turn_number in range(self._config.max_model_turns):
            state.model_iteration += 1
            allow_tools = (
                turn_number < self._config.max_model_turns - 1
                and state.tool_round < self._config.max_tool_rounds
                and state.tool_call_count < self._config.max_tool_calls
            )
            step = capture_step_context(
                agent_context=ctx,
                provider=self._provider,
                transport=self._model,
                history=turn_input,
                tools=self._tools.function_tools() if allow_tools else (),
                config=self._config,
                turn_number=turn_number,
            )

            completed: ModelStreamCompleted | None = None
            async for event in self._sample(step, tool_round=state.tool_round):
                if isinstance(event, ModelStreamCompleted):
                    completed = event
                else:
                    yield event
            if completed is None:
                raise AgentExecutionError("model stream did not complete")
            state.model_duration_ms += completed.duration_ms

            response = completed.response
            function_calls = response.function_calls
            answer_text = response.output_text

            if function_calls:
                if not allow_tools:
                    raise AgentExecutionError(
                        "model requested a tool after the safety limit"
                    )
                # Text before tool calls is model commentary — visible to the user
                # but must NOT be emitted as part of the final answer.
                if answer_text.strip():
                    yield CommentaryDelta(text=answer_text.strip(), turn=turn_number)

                turn_input = turn_input.extend(
                    ResponseItem(item=item) for item in completed.items
                )
                state.tool_round += 1
                execution_ctx = replace(
                    ctx,
                    retrieval_round=state.tool_round,
                    retrieval_query_count=len(function_calls),
                )
                for call in function_calls:
                    try:
                        arguments = call.parsed_arguments()
                    except ValueError:
                        arguments = {}
                    yield ToolStarted(
                        call_id=call.call_id,
                        name=call.name,
                        arguments=arguments,
                        activity_id=(
                            f"iteration-{state.model_iteration}-call-{call.call_id}"
                        ),
                        label=self._tools.public_label(call.name),
                        category=self._tools.public_category(call.name),
                    )
                observations = await self._execute_tools(
                    function_calls,
                    context=ToolContext(agent_context=execution_ctx),
                    remaining_calls=self._config.max_tool_calls - state.tool_call_count,
                    previous_signatures=state.executed_tool_signatures,
                )
                state.tool_call_count += sum(
                    1
                    for observation in observations
                    if observation.output.metadata.get("outcome")
                    not in {"invalid_arguments", "unknown_tool", "duplicate_call", "tool_call_limit"}
                )
                state.tool_duration_ms += sum(
                    observation.duration_ms for observation in observations
                )
                for observation in observations:
                    for evidence in observation.output.evidence:
                        existing = state.evidence.get(evidence.id)
                        if existing is None:
                            state.evidence[evidence.id] = evidence
                            yield CitationAvailable(
                                evidence=evidence_reference(evidence)
                            )
                        elif evidence.relevance_score is not None and (
                            existing.relevance_score is None
                            or evidence.relevance_score > existing.relevance_score
                        ):
                            state.evidence[evidence.id] = evidence
                    yield ToolCompleted(
                        call_id=observation.call.call_id,
                        name=observation.call.name,
                        activity_id=(
                            f"iteration-{state.model_iteration}-call-"
                            f"{observation.call.call_id}"
                        ),
                        error=observation.output.error,
                        duration_ms=observation.duration_ms,
                        result_count=observation.result_count,
                        label=self._tools.public_label(observation.call.name),
                        category=self._tools.public_category(observation.call.name),
                        status=observation.status,
                    )
                turn_input = turn_input.extend(
                    ResponseItem(
                        item=observation.provider_output(self._config.max_tool_context_characters)
                    )
                    for observation in observations
                )
                continue

            if not answer_text.strip():
                raise AgentExecutionError("model returned an empty response")

            # Emit final answer text through the citation buffer.
            async for event in self._final_response_events(completed, state):
                yield event

            if run_trace is not None:
                run_trace.complete(
                    answer=answer_text,
                    answer_characters=state.answer_character_count,
                    turn_count=state.model_iteration,
                    tool_call_count=state.tool_call_count,
                    sources_found=len(state.evidence),
                    sources_used=len(state.used_evidence_ids),
                )
            annotations = response.output_annotations
            yield RunCompleted(
                duration_ms=duration_ms(started_at),
                model_duration_ms=state.model_duration_ms,
                tool_duration_ms=state.tool_duration_ms,
                tool_call_count=state.tool_call_count,
                provider_annotations=list(annotations) or None,
            )
            return

        raise AgentExecutionError("model turn limit reached without a final response")

    async def _sample(
        self,
        step: StepContext,
        *,
        tool_round: int,
    ) -> AsyncIterator[AgentEvent | ModelStreamCompleted]:
        """Run one Sampling Request and report its timing to tracing."""

        started_at = perf_counter()
        rendered_history = (
            step.history.to_openai_input()
            if step.provider == "openai"
            else step.history.to_openrouter_messages()
        )
        trace_context = (
            self._tracing.model_turn(
                messages=rendered_history,
                ctx=step.agent_context,
                turn=step.turn_number,
                tool_round=tool_round,
            )
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as generation_trace:
            completed: ModelStreamCompleted | None = None
            try:
                async for event in run_sampling_request(
                    step, generation_trace=generation_trace
                ):
                    if isinstance(event, ModelStreamCompleted):
                        completed = event
                    else:
                        yield event
            except AgentExecutionError:
                if generation_trace is not None:
                    generation_trace.fail(
                        category="transport_error",
                        duration_ms=duration_ms(started_at),
                    )
                raise

            if completed is None:
                raise AgentExecutionError("provider stream did not complete")

            turn_duration_ms = duration_ms(started_at)
            if generation_trace is not None:
                generation_trace.complete(
                    response=completed.response,
                    duration_ms=turn_duration_ms,
                )

        yield replace(completed, duration_ms=turn_duration_ms)

    async def _final_response_events(
        self,
        completed: ModelStreamCompleted,
        state: ConversationRun,
    ) -> AsyncIterator[AgentEvent]:
        """Process text_deltas through the citation buffer and yield answer events.

        Each delta yields to the event loop so uvicorn can flush SSE frames
        incrementally rather than batching all chunks into one TCP write.
        """
        async for event in self._citations.render(
            completed.text_deltas,
            state.evidence,
            state.used_evidence_ids,
        ):
            if isinstance(event, FinalAnswerDelta):
                state.answer_character_count += len(event.text)
            yield event
            await asyncio.sleep(0)

    @staticmethod
    def _register_document_evidence(
        documents: Sequence[ConversationDocument],
        state: ConversationRun,
    ) -> list[CitationAvailable]:
        events: list[CitationAvailable] = []
        for document in documents:
            for evidence in document.evidence:
                if evidence.id in state.evidence:
                    continue
                state.evidence[evidence.id] = evidence
                events.append(
                    CitationAvailable(
                        evidence=evidence_reference(evidence).model_copy(
                            update={"relevance_score": None}
                        )
                    )
                )
        return events

    async def _execute_tools(
        self,
        calls: Sequence[FunctionCallItem],
        *,
        context: ToolContext,
        remaining_calls: int,
        previous_signatures: set[str],
    ) -> tuple[ToolObservation, ...]:
        """Apply runtime limits and execute independent tool calls concurrently."""

        observations: list[ToolObservation | None] = [None] * len(calls)
        pending: list[tuple[int, FunctionCallItem, dict[str, Any]]] = []
        for index, call in enumerate(calls):
            arguments = _decoded_arguments(call)
            if arguments is None:
                observations[index] = _error_observation(
                    call, "Invalid arguments for tool.", "invalid_arguments"
                )
                continue
            if self._tools.get(call.name) is None:
                observations[index] = _error_observation(
                    call, f"Unknown tool: {call.name}", "unknown_tool"
                )
                continue
            if not self._tools.arguments_are_valid(call.name, arguments):
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

        results = await asyncio.gather(
            *(
                self._execute_one_tool(call, arguments, context)
                for _, call, arguments in pending
            )
        )
        for (index, _, _), observation in zip(pending, results, strict=True):
            observations[index] = observation
        return tuple(item for item in observations if item is not None)

    async def _execute_one_tool(
        self,
        call: FunctionCallItem,
        arguments: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolObservation:
        tool = self._tools.get(call.name)
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
                    timeout=self._config.tool_timeout_seconds,
                )
                if trace is not None:
                    trace.complete(result=output)
        except TimeoutError:
            output = ToolOutput(
                content="",
                error="Tool execution timed out.",
                metadata={"outcome": "timeout", "result_count": 0},
            )
        except Exception:  # noqa: BLE001 - tool failure is an observation
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


def _error_observation(
    call: FunctionCallItem,
    error: str,
    outcome: str,
) -> ToolObservation:
    return ToolObservation(
        call=call,
        output=ToolOutput(
            content="",
            error=error,
            metadata={"outcome": outcome, "result_count": 0},
        ),
        duration_ms=0,
    )


def _decoded_arguments(call: FunctionCallItem) -> dict[str, Any] | None:
    try:
        return call.parsed_arguments()
    except ValueError:
        return None


def _tool_signature(name: str, arguments: Mapping[str, Any]) -> str:
    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{name}:{encoded}"


__all__ = ["TurnRequest"]
