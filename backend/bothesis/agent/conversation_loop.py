"""Orchestration: one user turn as a chain of OpenResponses responses.

The loop owns control flow and nothing else. It speaks only canonical Items:

    user turn
        └── sampling 1 ──> Response
                            ├── MessageItem(phase=commentary)
                            └── FunctionCallItem
                                    └── ToolExecutor ──> FunctionCallOutputItem
        └── sampling 2 ──> Response
                            └── MessageItem(phase=final_answer)

Every response's ``output`` is appended verbatim to the input of the next
sampling request, and each response records the previous one in
``previous_response_id``, so the several responses of one turn form an explicit
chain a client can follow. The loop never inspects a provider, never buffers a
delta, and never reconstructs response state itself: reconstruction belongs to
:class:`~bothesis.agent.reducer.ResponseReducer`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import nullcontext
from dataclasses import replace
from time import perf_counter
from typing import Any

from bothesis.agent import AgentConfig, AgentExecutionError, duration_ms
from bothesis.agent.citation_stream import CitationProjection
from bothesis.agent.conversation_compression import ConversationMemory
from bothesis.agent.models import (
    AgentContext,
    ConversationDocument,
    ConversationRun,
    ToolContext,
)
from bothesis.agent.protocol import (
    TERMINAL_EVENT_TYPES,
    Item,
    ReasoningItem,
    Response,
    ResponseOutputTextDeltaEvent,
    ResponseRequest,
    ResponseStreamEvent,
)
from bothesis.agent.reducer import ResponseReducer
from bothesis.agent.sampling import sample
from bothesis.agent.tools import ToolExecutor, ToolRegistry
from bothesis.agent.transports import ResponseStream
from bothesis.observability import AgentRunTrace, LangfuseTracing


class ConversationLoop:
    """Run one user turn across as many sampling requests as it takes."""

    def __init__(
        self,
        transport: ResponseStream,
        tools: ToolRegistry,
        *,
        memory: ConversationMemory,
        config: AgentConfig,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self._transport = transport
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

    async def run(
        self,
        user_message: str,
        ctx: AgentContext,
        *,
        run_trace: AgentRunTrace | None = None,
    ) -> AsyncIterator[ResponseStreamEvent]:
        """Yield the canonical event stream for one user turn."""

        state = ConversationRun(user_message=user_message)
        _register_document_evidence(ctx.documents, state)
        prepared = await self._memory.prepare(user_message, ctx)
        items: tuple[Item, ...] = prepared.items
        previous_response_id: str | None = None

        while True:
            if state.model_iteration >= self._config.max_model_turns:
                raise AgentExecutionError(
                    "sampling request limit reached without a final response"
                )
            state.model_iteration += 1
            allow_tools = (
                state.tool_round < self._config.max_tool_rounds
                and state.tool_call_count < self._config.max_tool_calls
                and (
                    ctx.allowed_tool_names is None
                    or bool(ctx.allowed_tool_names)
                )
            )
            request = self._request(
                items,
                ctx,
                instructions=prepared.instructions,
                allow_tools=allow_tools,
                previous_response_id=previous_response_id,
            )

            response: Response | None = None
            async for event, settled in self._sample(
                request, ctx, state, tool_round=state.tool_round
            ):
                response = settled or response
                yield event
            if response is None:
                raise AgentExecutionError("provider stream ended without a response")

            if response.status != "completed":
                # The terminal event already told the client why this response
                # stopped; the turn cannot continue from it.
                return

            previous_response_id = response.id
            items = (*items, *response.output)

            if response.function_calls:
                if not allow_tools:
                    raise AgentExecutionError(
                        "model requested a tool after the safety limit"
                    )
                items = (*items, *await self._execute_tools(response, ctx, state))
                continue

            answer = response.final_answer_text.strip()
            if not answer or self._tools.is_tool_arguments_payload(
                answer,
                ctx.allowed_tool_names,
            ):
                raise AgentExecutionError(
                    "model returned neither a final answer nor a valid tool call"
                )
            if run_trace is not None:
                run_trace.complete(
                    answer=answer,
                    answer_characters=len(answer),
                    turn_count=state.model_iteration,
                    tool_call_count=state.tool_call_count,
                    sources_found=len(state.evidence),
                    sources_used=len(state.used_evidence_ids),
                )
            return

    def _request(
        self,
        items: tuple[Item, ...],
        ctx: AgentContext,
        *,
        instructions: str | None,
        allow_tools: bool,
        previous_response_id: str | None,
    ) -> ResponseRequest:
        """Build the one immutable request this sampling attempt replays."""

        tools = (
            self._tools.function_tools(ctx.allowed_tool_names)
            if allow_tools
            else ()
        )
        return ResponseRequest(
            input=items,
            model=self._config.model or self._transport.model,
            instructions=instructions,
            tools=tools,
            tool_choice="auto" if tools else None,
            parallel_tool_calls=True if tools else None,
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_tokens,
            previous_response_id=previous_response_id,
            provider_options=dict(ctx.model_extra_body or {}),
        )

    async def _sample(
        self,
        request: ResponseRequest,
        ctx: AgentContext,
        state: ConversationRun,
        *,
        tool_round: int,
    ) -> AsyncIterator[tuple[ResponseStreamEvent, Response | None]]:
        """Stream one sampling request, yielding each event with the settled response.

        The second element is ``None`` until the response settles, then carries
        the fully reconstructed :class:`Response`.
        """

        started_at = perf_counter()
        reducer = ResponseReducer()
        projection = CitationProjection(state.evidence)
        trace_context = (
            self._tracing.model_turn(
                messages=_traced_items(request.input),
                ctx=ctx,
                turn=state.model_iteration,
                tool_round=tool_round,
            )
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as generation_trace:
            first_token_seen = False
            try:
                async for event in sample(
                    self._transport,
                    request,
                    max_retries=self._config.max_sampling_retries,
                    retry_base_delay_seconds=(
                        self._config.sampling_retry_base_delay_seconds
                    ),
                ):
                    for projected in projection.project(event):
                        reduced = reducer.apply(projected)
                        if (
                            not first_token_seen
                            and isinstance(reduced, ResponseOutputTextDeltaEvent)
                            and reduced.delta
                        ):
                            first_token_seen = True
                            if generation_trace is not None:
                                generation_trace.mark_first_token()
                        settled = (
                            reducer.response
                            if reduced.type in _SETTLING_TYPES
                            else None
                        )
                        yield reduced, settled
            except AgentExecutionError:
                if generation_trace is not None:
                    generation_trace.fail(
                        category="transport_error",
                        duration_ms=duration_ms(started_at),
                    )
                raise

            response = reducer.response
            state.used_evidence_ids.update(projection.used_evidence_ids)
            state.model_duration_ms += duration_ms(started_at)
            if response is not None and generation_trace is not None:
                generation_trace.complete(
                    response=response,
                    duration_ms=duration_ms(started_at),
                    reasoning_summary=_reasoning_summary(response) or None,
                )

    async def _execute_tools(
        self,
        response: Response,
        ctx: AgentContext,
        state: ConversationRun,
    ) -> tuple[Item, ...]:
        """Execute the response's function calls and return their observations."""

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
            allowed_tool_names=ctx.allowed_tool_names,
        )
        state.tool_call_count += batch.executed_call_count
        state.tool_duration_ms += batch.duration_ms
        return batch.output_items


_SETTLING_TYPES = TERMINAL_EVENT_TYPES | {"error"}
"""The events after which the reconstructed response is final.

A stream-level ``error`` settles the response as failed without a terminal
lifecycle event, so it ends the turn the same way: the client has already been
told why."""


def _traced_items(items: Sequence[Item]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json", exclude_none=True) for item in items]


def _reasoning_summary(response: Response) -> str:
    return "".join(
        item.summary_text for item in response.output if isinstance(item, ReasoningItem)
    )


def _register_document_evidence(
    documents: Sequence[ConversationDocument], state: ConversationRun
) -> None:
    for document in documents:
        for evidence in document.evidence:
            state.evidence.setdefault(evidence.id, evidence)


__all__ = ["ConversationLoop"]
