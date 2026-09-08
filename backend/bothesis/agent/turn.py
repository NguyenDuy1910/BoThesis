"""Run one user turn as repeated provider-neutral sampling steps."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import nullcontext
from time import perf_counter
from typing import Any

from bothesis.agent import AgentExecutionError, StepContext, TurnContext, duration_ms
from bothesis.agent.citation_stream import CitationProjection
from bothesis.agent.models import ConversationDocument
from bothesis.agent.protocol import (
    TERMINAL_EVENT_TYPES,
    Item,
    Prompt,
    ReasoningItem,
    Response,
    ResponseOutputTextDeltaEvent,
    ResponseStreamEvent,
)
from bothesis.agent.reducer import ResponseReducer
from bothesis.agent.sampling import sample
from bothesis.agent.session import Session
from bothesis.agent.tools import ToolOrchestrator


async def run_turn(session: Session, turn: TurnContext) -> AsyncIterator[ResponseStreamEvent]:
    """Stream one turn, recapturing StepContext before every model request."""

    _register_document_evidence(turn.environment.agent_context.documents, turn)
    await session.context_manager.start_turn(turn.user_input, turn.environment.agent_context)
    orchestrator = ToolOrchestrator(
        timeout_seconds=session.configuration.tool_timeout_seconds,
        max_output_characters=session.configuration.max_tool_context_characters,
        tracing=session.services.tracing,
    )
    previous_response_id: str | None = None
    while True:
        if turn.model_iteration >= session.configuration.max_model_turns:
            raise AgentExecutionError("sampling request limit reached without a final response")
        turn.model_iteration += 1
        step_context = await session.capture_step_context(turn)
        prompt = _build_prompt(session, step_context, previous_response_id)
        response: Response | None = None
        async for event, settled in run_sampling_request(session, step_context, prompt):
            response = settled or response
            yield event
        if response is None:
            raise AgentExecutionError("provider stream ended without a response")
        if response.status != "completed":
            return

        previous_response_id = response.id
        session.context_manager.record(response.output)
        if response.function_calls:
            if not step_context.tool_router.model_visible_specs:
                raise AgentExecutionError("model requested a tool after the safety limit")
            turn.tool_round += 1
            batch = await orchestrator.execute(
                response.function_calls,
                session=session,
                step_context=step_context,
                remaining_calls=session.configuration.max_tool_calls - turn.tool_call_count,
            )
            turn.tool_call_count += batch.executed_call_count
            turn.tool_duration_ms += batch.duration_ms
            session.context_manager.record(batch.output_items)
            continue

        answer = response.final_answer_text.strip()
        if not answer or session.tool_registry.is_tool_arguments_payload(
            answer, step_context.tool_router.model_visible_specs and tuple(tool.name for tool in step_context.tool_router.model_visible_specs)
        ):
            raise AgentExecutionError("model returned neither a final answer nor a valid tool call")
        _complete_trace(session, turn, answer)
        return


def _build_prompt(session: Session, step_context: StepContext, previous_response_id: str | None) -> Prompt:
    settings = step_context.settings
    tools = step_context.tool_router.model_visible_specs
    return Prompt(
        input=session.context_manager.for_prompt(),
        model=settings.model,
        instructions=session.context_manager.instructions,
        tools=tools,
        tool_choice="auto" if tools else None,
        parallel_tool_calls=settings.parallel_tool_calls if tools else None,
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        previous_response_id=previous_response_id,
        provider_options=settings.provider_options,
    )


async def run_sampling_request(
    session: Session, step_context: StepContext, prompt: Prompt
) -> AsyncIterator[tuple[ResponseStreamEvent, Response | None]]:
    """Stream exactly one sampling request and reconstruct canonical output."""

    turn = step_context.turn
    started_at = perf_counter()
    reducer = ResponseReducer()
    projection = CitationProjection(turn.evidence, references=turn.references)
    tracing = session.services.tracing
    trace_context = (
        tracing.model_turn(
            messages=_traced_items(prompt.input),
            ctx=step_context.environment.agent_context,
            turn=turn.model_iteration,
            tool_round=turn.tool_round,
        )
        if tracing is not None
        else nullcontext(None)
    )
    with trace_context as generation_trace:
        first_token_seen = False
        try:
            async for event in sample(
                session.model,
                prompt,
                max_retries=session.configuration.max_sampling_retries,
                retry_base_delay_seconds=session.configuration.sampling_retry_base_delay_seconds,
            ):
                for projected in projection.project(event):
                    reduced = reducer.apply(projected)
                    if not first_token_seen and isinstance(reduced, ResponseOutputTextDeltaEvent) and reduced.delta:
                        first_token_seen = True
                        if generation_trace is not None:
                            generation_trace.mark_first_token()
                    settled = reducer.response if reduced.type in _SETTLING_TYPES else None
                    yield reduced, settled
        except AgentExecutionError:
            if generation_trace is not None:
                generation_trace.fail(category="transport_error", duration_ms=duration_ms(started_at))
            raise
        finally:
            turn.used_evidence_ids.update(projection.used_evidence_ids)
            turn.model_duration_ms += duration_ms(started_at)
        if reducer.response is not None and generation_trace is not None:
            generation_trace.complete(
                response=reducer.response,
                duration_ms=duration_ms(started_at),
                reasoning_summary=_reasoning_summary(reducer.response) or None,
            )


def _complete_trace(session: Session, turn: TurnContext, answer: str) -> None:
    # The public Agent owns the encompassing run trace.  This helper keeps the
    # turn loop provider-neutral and intentionally does not retain trace state.
    del session, turn, answer


_SETTLING_TYPES = TERMINAL_EVENT_TYPES | {"error"}


def _traced_items(items: Sequence[Item]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json", exclude_none=True) for item in items]


def _reasoning_summary(response: Response) -> str:
    return "".join(item.summary_text for item in response.output if isinstance(item, ReasoningItem))


def _register_document_evidence(documents: Sequence[ConversationDocument], turn: TurnContext) -> None:
    for document in documents:
        for evidence in document.evidence:
            turn.evidence.setdefault(evidence.id, evidence)


__all__ = ["run_sampling_request", "run_turn"]
