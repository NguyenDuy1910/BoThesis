"""The semantic Turn loop: sample, execute requested tools, then continue."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import nullcontext
from dataclasses import replace
from time import perf_counter

from bothesis.agent import AgentConfig, AgentExecutionError, ModelStreamCompleted, duration_ms
from bothesis.agent.conversation_compression import ConversationMemory
from bothesis.agent.models import (
    AgentContext,
    ConversationDocument,
    ConversationRun,
    Evidence,
    ToolContext,
)
from bothesis.agent.protocol import ResponseStreamEvent, SamplingRequestOutput
from bothesis.agent.sampling_request import run_sampling_request
from bothesis.agent.step_context import Provider, StepContext, capture_step_context
from bothesis.agent.tools import ToolExecutor, ToolRegistry
from bothesis.agent.transports.openai import OpenAITransport
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.agent.turn_input import ResponseItem
from bothesis.observability import AgentRunTrace, LangfuseTracing


class TurnRequest:
    """Run one user Turn across zero or more follow-up sampling responses."""

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
    ) -> AsyncIterator[ResponseStreamEvent]:
        """Yield only client semantic state; runtime instrumentation stays private."""

        state = ConversationRun(user_message=user_message)
        self._register_document_evidence(ctx.documents, state)
        turn_input = await self._memory.prepare(user_message, ctx)

        while True:
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
            step = capture_step_context(
                agent_context=ctx,
                provider=self._provider,
                transport=self._model,
                history=turn_input,
                tools=self._tools.function_tools() if allow_tools else (),
                config=self._config,
                sampling_number=sampling_number,
            )

            completed: ModelStreamCompleted | None = None
            async for event in self._sample(step, tool_round=state.tool_round, evidence=state.evidence):
                if isinstance(event, ModelStreamCompleted):
                    completed = event
                else:
                    yield event
            if completed is None:
                raise AgentExecutionError("model stream did not complete")

            state.model_duration_ms += completed.duration_ms
            state.used_evidence_ids.update(completed.used_evidence_ids)
            response = completed.response
            output = SamplingRequestOutput.from_response(response)

            if response.status != "completed":
                # The terminal response event already communicates incomplete
                # provider state to the client; it is not a successful Turn.
                return

            if output.needs_follow_up:
                if not allow_tools:
                    raise AgentExecutionError("model requested a tool after the safety limit")
                turn_input = turn_input.extend(
                    tuple(ResponseItem(item=item) for item in completed.items)
                )
                state.tool_round += 1
                execution_ctx = replace(
                    ctx,
                    retrieval_round=state.tool_round,
                    retrieval_query_count=len(response.function_calls),
                )
                batch = await self._tool_executor.execute(
                    response.function_calls,
                    context=ToolContext(agent_context=execution_ctx),
                    remaining_calls=self._config.max_tool_calls - state.tool_call_count,
                    previous_signatures=state.executed_tool_signatures,
                    evidence=state.evidence,
                )
                state.tool_call_count += batch.executed_call_count
                state.tool_duration_ms += batch.duration_ms
                turn_input = turn_input.extend(
                    tuple(ResponseItem(item=item) for item in batch.output_items)
                )
                continue

            if (
                output.last_agent_message is None
                or self._tools.is_tool_arguments_payload(output.last_agent_message)
            ):
                raise AgentExecutionError(
                    "model returned neither a final answer nor a valid tool call"
                )
            if run_trace is not None:
                run_trace.complete(
                    answer=output.last_agent_message,
                    answer_characters=len(output.last_agent_message),
                    turn_count=state.model_iteration,
                    tool_call_count=state.tool_call_count,
                    sources_found=len(state.evidence),
                    sources_used=len(state.used_evidence_ids),
                )
            return

    async def _sample(
        self,
        step: StepContext,
        *,
        tool_round: int,
        evidence: dict[str, Evidence],
    ) -> AsyncIterator[ResponseStreamEvent | ModelStreamCompleted]:
        """Trace one immutable sampling request without exposing trace events."""

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
                turn=step.sampling_number,
                tool_round=tool_round,
            )
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as generation_trace:
            completed: ModelStreamCompleted | None = None
            try:
                async for event in run_sampling_request(
                    step,
                    self._model,
                    generation_trace=generation_trace,
                    evidence=evidence,
                ):
                    if isinstance(event, ModelStreamCompleted):
                        completed = event
                    else:
                        yield event
            except AgentExecutionError:
                if generation_trace is not None:
                    generation_trace.fail(
                        category="transport_error", duration_ms=duration_ms(started_at)
                    )
                raise

            if completed is None:
                raise AgentExecutionError("provider stream did not complete")
            completed = replace(completed, duration_ms=duration_ms(started_at))
            if generation_trace is not None:
                generation_trace.complete(
                    response=completed.response, duration_ms=completed.duration_ms
                )
        yield completed

    @staticmethod
    def _register_document_evidence(
        documents: Sequence[ConversationDocument], state: ConversationRun
    ) -> None:
        for document in documents:
            for evidence in document.evidence:
                state.evidence.setdefault(evidence.id, evidence)


__all__ = ["TurnRequest"]
