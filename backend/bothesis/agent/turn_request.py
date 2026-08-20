"""One user request executed end to end: the Turn Loop.

A Turn Request represents the full execution of one user request. It is not
one LLM call — it loops through as many Sampling Requests
(:func:`~bothesis.agent.sampling_request.run_sampling_request`, which owns the
provider retry loop and the canonical response-stream processing) as it takes
to alternate model decisions and tool observations into a final answer.
:class:`~bothesis.agent.conversation_session.ConversationSession` constructs one
fresh ``TurnRequest`` per user message and delegates entirely to it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import nullcontext
from dataclasses import replace
from time import perf_counter
from bothesis.agent import (
    AgentConfig,
    AgentExecutionError,
    ModelStreamCompleted,
    TextDelta,
    duration_ms,
)
from bothesis.agent.conversation_compression import ConversationMemory
from bothesis.agent.message_emitter import MessageEmitter
from bothesis.agent.models import (
    AgentContext,
    ConversationDocument,
    ConversationRun,
    ToolContext,
)
from bothesis.agent.protocol import (
    EvidenceItem,
    ItemCompleted,
    ItemStarted,
    ReasoningSummaryDelta,
    RuntimeStreamEvent,
    SamplingRequestOutput,
    TurnCompleted,
    TurnStarted,
)
from bothesis.agent.sampling_request import run_sampling_request
from bothesis.agent.step_context import Provider, StepContext, capture_step_context
from bothesis.agent.tools import ToolExecutionBatch, ToolExecutor, ToolRegistry
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
        self._messages = MessageEmitter()
        self._tool_executor = ToolExecutor(
            tools,
            timeout_seconds=config.tool_timeout_seconds,
            max_output_characters=config.max_tool_context_characters,
            tracing=tracing,
        )

    async def run_turn(
        self,
        user_message: str,
        ctx: AgentContext,
        *,
        run_trace: AgentRunTrace | None,
    ) -> AsyncIterator[RuntimeStreamEvent]:
        """Execute one user Turn through repeated model samplings."""

        started_at = perf_counter()
        state = ConversationRun(user_message=user_message)

        yield TurnStarted()
        for item in self._register_document_evidence(ctx.documents, state):
            yield ItemStarted(item=item)
            yield ItemCompleted(item=item)

        turn_input = await self._memory.prepare(user_message, ctx)

        while True:
            # Safety guard only — this does not drive the semantic loop.
            if state.model_iteration >= self._config.max_model_turns:
                raise AgentExecutionError(
                    "sampling request limit reached without a final response"
                )

            state.model_iteration += 1
            sampling_number = state.model_iteration

            allow_tools = (
                state.tool_round < self._config.max_tool_rounds
                and state.tool_call_count < self._config.max_tool_calls
            )

            # One fresh immutable snapshot per Sampling Request.
            step_input = capture_step_context(
                agent_context=ctx,
                provider=self._provider,
                transport=self._model,
                history=turn_input,
                tools=self._tools.function_tools() if allow_tools else (),
                config=self._config,
                turn_number=sampling_number,
            )

            completed: ModelStreamCompleted | None = None
            message_started = False
            streamed_character_count = 0

            async for event in self._sample(
                step_input,
                tool_round=state.tool_round,
            ):
                if isinstance(event, ModelStreamCompleted):
                    completed = event
                elif isinstance(event, TextDelta):
                    if not message_started:
                        yield self._messages.start(
                            item_id=f"turn-message-{sampling_number}"
                        )
                        message_started = True
                    for message_event in self._messages.delta(
                        event.text,
                        evidence=state.evidence,
                        render_citations=bool(state.evidence),
                    ):
                        streamed_character_count += len(message_event.delta)
                        yield message_event

            if completed is None:
                raise AgentExecutionError("model stream did not complete")

            state.model_duration_ms += completed.duration_ms

            response = completed.response
            output = SamplingRequestOutput.from_response(response)

            # Model requested actions → Turn continues.

            if output.needs_follow_up:
                if not allow_tools:
                    raise AgentExecutionError(
                        "model requested a tool after the safety limit"
                    )

                function_calls = response.function_calls

                if message_started:
                    for message_event in self._messages.complete(phase="commentary"):
                        if message_event.type == "item.delta":
                            streamed_character_count += len(message_event.delta)
                        yield message_event

                # Persist semantic model output before executing its requested tools.
                turn_input = turn_input.extend(
                    ResponseItem(item=item)
                    for item in completed.items
                )

                state.tool_round += 1

                execution_ctx = replace(
                    ctx,
                    retrieval_round=state.tool_round,
                    retrieval_query_count=len(function_calls),
                )

                tool_batch: ToolExecutionBatch | None = None
                async for tool_event in self._tool_executor.execute(
                    function_calls,
                    context=ToolContext(agent_context=execution_ctx),
                    remaining_calls=(
                        self._config.max_tool_calls
                        - state.tool_call_count
                    ),
                    previous_signatures=state.executed_tool_signatures,
                    sampling_number=sampling_number,
                    evidence=state.evidence,
                ):
                    if isinstance(tool_event, ToolExecutionBatch):
                        tool_batch = tool_event
                    else:
                        yield tool_event
                if tool_batch is None:
                    raise AgentExecutionError("tool execution did not complete")
                state.tool_call_count += tool_batch.executed_call_count
                state.tool_duration_ms += tool_batch.duration_ms

                # Tool observations become input for the NEXT sampling.
                turn_input = turn_input.extend(
                    ResponseItem(item=item) for item in tool_batch.output_items
                )

                continue

            # No tool call → model should have completed the Turn.

            if (
                output.last_agent_message is None
                or self._tools.is_tool_arguments_payload(output.last_agent_message)
            ):
                raise AgentExecutionError(
                    "model returned neither a final answer nor a valid tool call"
                )

            if not message_started:
                raise AgentExecutionError("model returned text without streaming deltas")
            for message_event in self._messages.complete(phase="final_answer"):
                if message_event.type == "item.delta":
                    streamed_character_count += len(message_event.delta)
                yield message_event
            state.answer_character_count += streamed_character_count
            state.used_evidence_ids.update(self._messages.used_evidence_ids)
            for evidence_id in state.used_evidence_ids:
                yield ItemCompleted(
                    item=_evidence_item(state.evidence[evidence_id], status="used")
                )
            if run_trace is not None:
                run_trace.complete(
                    answer=output.last_agent_message,
                    answer_characters=state.answer_character_count,
                    turn_count=state.model_iteration,
                    tool_call_count=state.tool_call_count,
                    sources_found=len(state.evidence),
                    sources_used=len(state.used_evidence_ids),
                )
            yield TurnCompleted(
                duration_ms=duration_ms(started_at),
                model_duration_ms=state.model_duration_ms,
                tool_duration_ms=state.tool_duration_ms,
                tool_call_count=state.tool_call_count,
            )
            return

    async def _sample(
        self,
        step: StepContext,
        *,
        tool_round: int,
    ) -> AsyncIterator[TextDelta | ModelStreamCompleted]:
        """Run one Sampling Request, forwarding text while retaining control metadata."""

        started_at = perf_counter()
        rendered_history = (
            step.history.to_openai_input()
            if step.model_info.provider == "openai"
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
            reasoning_summary_parts: list[str] = []
            try:
                async for event in run_sampling_request(
                    step, self._model, generation_trace=generation_trace
                ):
                    if isinstance(event, ModelStreamCompleted):
                        completed = event
                    elif isinstance(event, ReasoningSummaryDelta):
                        reasoning_summary_parts.append(event.delta)
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
                    reasoning_summary=(
                        "".join(reasoning_summary_parts) or None
                    ),
                )

        yield replace(completed, duration_ms=turn_duration_ms)

    @staticmethod
    def _register_document_evidence(
        documents: Sequence[ConversationDocument],
        state: ConversationRun,
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for document in documents:
            for evidence in document.evidence:
                if evidence.id in state.evidence:
                    continue
                state.evidence[evidence.id] = evidence
                items.append(_evidence_item(evidence, relevance_score=None))
        return items


def _evidence_item(
    evidence: Evidence,
    *,
    relevance_score: float | None | object = ...,
    status: str = "found",
) -> EvidenceItem:
    from bothesis.agent import evidence_reference

    values = evidence_reference(evidence).model_dump()
    values["status"] = status
    if relevance_score is not ...:
        values["relevance_score"] = relevance_score
    return EvidenceItem(**values)

__all__ = ["TurnRequest"]
