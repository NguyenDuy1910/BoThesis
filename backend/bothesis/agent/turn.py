"""Run one user turn as repeated provider-neutral sampling steps."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from time import perf_counter

from bothesis.agent import (
    AgentExecutionError,
    AgentStreamEvent,
    StepContext,
    TurnContext,
    duration_ms,
)
from bothesis.agent.citation_stream import CitationProjection
from bothesis.agent.protocol import (
    TERMINAL_EVENT_TYPES,
    MessageItem,
    Prompt,
    Response,
    ResponseOutputTextDeltaEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseStreamEvent,
    ToolCall,
    ToolCompletedEvent,
    ToolProgressEvent,
    ToolStartedEvent,
    FunctionTool,
)
from bothesis.agent.reducer import ResponseReducer
from bothesis.agent.sampling import sample
from bothesis.agent.session import Session
from bothesis.agent.tools import ToolExecutionBatch, ToolOrchestrator, ToolProgress
from bothesis.observability import TraceSerializer


async def run_turn(session: Session, turn: TurnContext) -> AsyncIterator[AgentStreamEvent]:
    """Stream one turn, recapturing StepContext before every model request."""

    await session.context_manager.start_turn(turn, session.resource_resolver)
    orchestrator = ToolOrchestrator(
        timeout_seconds=session.configuration.tool_timeout_seconds,
        max_output_characters=session.configuration.max_tool_context_characters,
        tracer=session.tracer,
    )
    previous_response_id: str | None = None
    while True:
        if turn.model_iteration >= session.configuration.max_model_turns:
            raise AgentExecutionError("sampling request limit reached without a final response")
        turn.model_iteration += 1
        step_context = await session.capture_step_context(turn)
        prompt = _build_prompt(step_context, previous_response_id)
        response: Response | None = None
        async for event, settled in run_sampling_request(session, turn, step_context, prompt):
            response = settled or response
            yield event
        if response is None:
            raise AgentExecutionError("provider stream ended without a response")
        if response.status != "completed":
            return

        previous_response_id = response.id
        session.context_manager.record(turn, response.output)
        if response.function_calls:
            if not step_context.tools:
                raise AgentExecutionError("model requested a tool after the safety limit")
            turn.tool_round += 1
            batch: ToolExecutionBatch | None = None
            async for event, completed_batch in _execute_tools(
                orchestrator,
                response.function_calls,
                session=session,
                turn=turn,
                step_context=step_context,
                remaining_calls=session.configuration.max_tool_calls - turn.tool_call_count,
            ):
                if event is not None:
                    yield event
                else:
                    batch = completed_batch
            assert batch is not None
            turn.tool_call_count += batch.executed_call_count
            turn.tool_duration_ms += batch.duration_ms
            session.context_manager.record(turn, batch.output_items)
            if batch.model_content:
                session.context_manager.record(turn, (
                    MessageItem(role="user", content=batch.model_content),
                ))
            for output_index, item in enumerate(
                batch.output_items, start=len(response.output)
            ):
                yield ResponseOutputItemAddedEvent(output_index=output_index, item=item)
                yield ResponseOutputItemDoneEvent(output_index=output_index, item=item)
            continue

        answer = response.final_answer_text.strip()
        if not answer or session.tool_registry.is_tool_arguments_payload(
            answer, step_context.tools and tuple(
                tool.name
                for tool in step_context.tools
                if isinstance(tool, FunctionTool)
            )
        ):
            raise AgentExecutionError("model returned neither a final answer nor a valid tool call")
        return


async def _execute_tools(
    orchestrator: ToolOrchestrator,
    calls: tuple[ToolCall, ...],
    *,
    session: Session,
    turn: TurnContext,
    step_context: StepContext,
    remaining_calls: int,
) -> AsyncIterator[tuple[AgentStreamEvent | None, ToolExecutionBatch | None]]:
    """Forward actual runtime activity while tool calls execute concurrently."""

    progress: asyncio.Queue[ToolProgress] = asyncio.Queue()

    async def report(update: ToolProgress) -> None:
        await progress.put(update)

    execution = asyncio.create_task(
        orchestrator.execute(
            calls,
            session=session,
            turn=turn,
            step_context=step_context,
            tool_router=session.tool_router(step_context),
            resources=session.resources_for(step_context),
            remaining_calls=remaining_calls,
            on_progress=report,
        )
    )
    next_update = asyncio.create_task(progress.get())
    try:
        while not execution.done():
            complete, _ = await asyncio.wait(
                (execution, next_update), return_when=asyncio.FIRST_COMPLETED
            )
            if next_update in complete:
                yield _runtime_activity_event(next_update.result()), None
                next_update = asyncio.create_task(progress.get())
        if next_update.done():
            yield _runtime_activity_event(next_update.result()), None
        else:
            next_update.cancel()
        while not progress.empty():
            yield _runtime_activity_event(progress.get_nowait()), None
        yield None, await execution
    finally:
        if not next_update.done():
            next_update.cancel()
        if not execution.done():
            execution.cancel()


def _runtime_activity_event(update: ToolProgress) -> AgentStreamEvent:
    if update.event_type == "started":
        return ToolStartedEvent(call_id=update.call_id, tool_name=update.tool_name)
    if update.event_type == "completed":
        status = update.data.get("status")
        result_count = update.data.get("result_count")
        duration_ms = update.data.get("duration_ms")
        return ToolCompletedEvent(
            call_id=update.call_id,
            tool_name=update.tool_name,
            status=(
                status
                if status in {"completed", "failed", "timeout", "skipped"}
                else "failed"
            ),
            result_count=(
                result_count
                if isinstance(result_count, int) and result_count >= 0
                else None
            ),
            duration_ms=(
                duration_ms
                if isinstance(duration_ms, int) and duration_ms >= 0
                else 0
            ),
        )
    return ToolProgressEvent(
        call_id=update.call_id,
        tool_name=update.tool_name,
        data=update.data,
    )


def _build_prompt(step_context: StepContext, previous_response_id: str | None) -> Prompt:
    settings = step_context.settings
    tools = step_context.tools
    return Prompt(
        input=step_context.input_items,
        model=settings.model,
        instructions=step_context.instructions,
        tools=tools,
        tool_choice="auto" if tools else None,
        parallel_tool_calls=settings.parallel_tool_calls if tools else None,
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        previous_response_id=previous_response_id,
        provider_options=settings.provider_options,
    )


async def run_sampling_request(
    session: Session, turn: TurnContext, step_context: StepContext, prompt: Prompt
) -> AsyncIterator[tuple[ResponseStreamEvent, Response | None]]:
    """Stream exactly one sampling request and reconstruct canonical output."""

    started_at = perf_counter()
    reducer = ResponseReducer()
    projection = CitationProjection(turn.evidence, references=turn.references)
    # Trace start: this generation contains the normalized and provider request.
    with session.tracer.generation(
        "model.sample",
        model=prompt.model,
        attributes={
            "step": turn.model_iteration,
            "tool_round": turn.tool_round,
            "provider": session.model.provider,
        },
        input=TraceSerializer.full(
            TraceSerializer.model_input(
                prompt,
                step_context=step_context,
            )
        ),
    ) as generation_trace:
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
                        generation_trace.mark_first_token()
                    settled = reducer.response if reduced.type in _SETTLING_TYPES else None
                    yield reduced, settled
        finally:
            turn.used_evidence_ids.update(projection.used_evidence_ids)
            turn.model_duration_ms += duration_ms(started_at)
        if reducer.response is not None:
            generation_trace.set_output(
                TraceSerializer.full(TraceSerializer.model_output(reducer.response))
            )
        # Trace end: the settled response and token timing are now available.


_SETTLING_TYPES = TERMINAL_EVENT_TYPES | {"error"}


__all__ = ["run_sampling_request", "run_turn"]
