"""Bounded, model-driven enterprise agent orchestration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any
from xml.sax.saxutils import escape

from bothesis.agent.capabilities import (
    CapabilityExecutionError,
    ConversationCompression,
    StructuredCapabilityExecutor,
)
from bothesis.agent.models import (
    AgentContext,
    AgentEvent,
    CitationAvailable,
    CitationEvent,
    ConversationMessage,
    GenerationCompleted,
    GenerationStarted,
    MessageDelta,
    ModelTurn,
    RunCompleted,
    RunFailed,
    RunStarted,
    TextDelta,
    ToolCall,
    ToolCompleted,
    ToolResult,
    ToolStarted,
    TurnCompleted,
    TurnStarted,
)
from bothesis.agent.prompts.template_render import render_chat_base
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.transports.base import LLMTransport, LLMTransportError
from bothesis.chat.agent_state import KnowledgeAgentState
from bothesis.chat.agent_utils import (
    duration_ms,
    evidence_reference,
    evidence_score,
    limit_tool_result,
    result_count,
    result_duration,
    tool_signature,
)
from bothesis.chat.citation_processor import process_citation_buffer
from bothesis.chat.compression import ConversationContextPolicy
from bothesis.chat.event_emitter import ModelTurnAccumulator, StreamCompleted
from bothesis.observability import AgentRunTrace, LangfuseTracing

ModelMessage = dict[str, Any]


class AgentExecutionError(RuntimeError):
    """A model turn could not safely complete the chat request."""


@dataclass(frozen=True, slots=True)
class ToolRoundCompleted:
    messages: list[ModelMessage]


class AgentLoop:
    """Let the model answer or select tools inside a small bounded loop."""

    def __init__(
        self,
        transport: LLMTransport,
        registry: ToolRegistry,
        *,
        capabilities: StructuredCapabilityExecutor | None = None,
        max_model_turns: int = 3,
        max_tool_rounds: int = 2,
        max_tool_calls: int = 6,
        max_history_messages: int = 8,
        max_history_characters: int = 8_000,
        history_compression_threshold: int = 4_000,
        max_compressed_history_characters: int = 2_000,
        max_tool_result_characters: int = 10_000,
        max_tool_context_characters: int = 12_000,
        max_user_message_characters: int = 4_000,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        if max_model_turns < 1:
            raise ValueError("max_model_turns must be at least one")
        if max_tool_rounds < 0 or max_tool_rounds >= max_model_turns:
            raise ValueError("max_tool_rounds must be lower than max_model_turns")
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least one")
        if (
            min(
                max_tool_result_characters,
                max_tool_context_characters,
                max_user_message_characters,
            )
            < 1
        ):
            raise ValueError("agent context limits must be at least one")

        self._transport = transport
        self._registry = registry
        self._tracing = tracing
        self._capabilities = capabilities or StructuredCapabilityExecutor(
            transport,
            tracing=tracing,
        )
        self._max_model_turns = max_model_turns
        self._max_tool_rounds = max_tool_rounds
        self._max_tool_calls = max_tool_calls
        self._conversation_context = ConversationContextPolicy(
            max_messages=max_history_messages,
            max_characters=max_history_characters,
            compression_threshold=history_compression_threshold,
            max_compressed_characters=max_compressed_history_characters,
        )
        self._max_tool_result_characters = max_tool_result_characters
        self._max_tool_context_characters = max_tool_context_characters
        self._max_user_message_characters = max_user_message_characters

    async def run_stream(
        self,
        user_message: str,
        ctx: AgentContext,
    ) -> AsyncIterator[AgentEvent]:
        normalized_message = user_message.strip()
        if not normalized_message:
            yield RunFailed(error="message must not be empty")
            return
        if len(normalized_message) > self._max_user_message_characters:
            yield RunFailed(error="message exceeds the allowed length")
            return
        if not ctx.tenant_id or not ctx.user_id:
            yield RunFailed(error="tenant and user context are required")
            return

        trace_context = (
            self._tracing.agent_run(user_message=normalized_message, ctx=ctx)
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as run_trace:
            try:
                async for event in self._run_validated_stream(
                    normalized_message,
                    ctx,
                    run_trace,
                ):
                    yield event
            except (AgentExecutionError, LLMTransportError):
                if run_trace is not None:
                    run_trace.fail(stage="model")
                yield RunFailed(error="model response failed")

    async def _run_validated_stream(
        self,
        user_message: str,
        ctx: AgentContext,
        run_trace: AgentRunTrace | None,
    ) -> AsyncIterator[AgentEvent]:
        started_at = perf_counter()
        state = KnowledgeAgentState(user_message=user_message)
        yield RunStarted(
            conversation_id=ctx.conversation_id,
            request_id=ctx.request_id,
        )
        messages = await self._initial_messages(
            history=ctx.history,
            user_message=user_message,
            ctx=ctx,
            state=state,
        )

        for turn_number in range(self._max_model_turns):
            state.model_turn_count += 1
            state.step += 1
            yield TurnStarted(turn=turn_number)
            yield GenerationStarted(turn=turn_number)

            tools_available = self._tools_available(turn_number, state)
            tools = self._registry.schemas() if tools_available else []
            completed: StreamCompleted | None = None
            async for event in self._stream_model_turn(
                messages=messages,
                tools=tools,
                ctx=ctx,
                state=state,
                turn_number=turn_number,
            ):
                if isinstance(event, StreamCompleted):
                    completed = event
                else:
                    yield event
            if completed is None:
                raise AgentExecutionError("model stream did not complete")
            turn = completed.turn
            generation_kind = "next_step" if turn.tool_calls else "final_response"
            yield GenerationCompleted(
                turn=turn_number,
                generation_kind=generation_kind,
                finish_reason=turn.finish_reason,
                tool_call_count=len(turn.tool_calls),
                selected_tools=[call.name for call in turn.tool_calls],
                duration_ms=completed.duration_ms,
            )

            if not turn.tool_calls:
                if not turn.text.strip():
                    raise AgentExecutionError("model returned an empty response")
                async for event in self._complete_run(
                    state=state,
                    completed_turn=turn,
                    started_at=started_at,
                    run_trace=run_trace,
                    turn_number=turn_number,
                ):
                    yield event
                return
            if not tools_available:
                raise AgentExecutionError(
                    "model requested a tool after the safety limit"
                )

            messages.append(_assistant_tool_message(turn))
            round_completed: ToolRoundCompleted | None = None
            async for event in self._run_tool_round(
                calls=turn.tool_calls,
                ctx=ctx,
                state=state,
            ):
                if isinstance(event, ToolRoundCompleted):
                    round_completed = event
                else:
                    yield event
            if round_completed is None:
                raise AgentExecutionError("tool round did not complete")
            messages.extend(round_completed.messages)
            yield TurnCompleted(turn=turn_number, outcome="tool")

        raise AgentExecutionError("model-turn limit reached without a final response")

    def _tools_available(
        self,
        turn_number: int,
        state: KnowledgeAgentState,
    ) -> bool:
        return bool(self._registry.schemas()) and all(
            (
                turn_number < self._max_model_turns - 1,
                state.tool_round < self._max_tool_rounds,
                state.tool_call_count < self._max_tool_calls,
            )
        )

    async def _initial_messages(
        self,
        *,
        history: tuple[ConversationMessage, ...],
        user_message: str,
        ctx: AgentContext,
        state: KnowledgeAgentState,
    ) -> list[ModelMessage]:
        bounded_conversation = self._conversation_context.bounded(history)
        messages: list[ModelMessage] = [
            {"role": "system", "content": render_chat_base()}
        ]
        if self._conversation_context.needs_compression(bounded_conversation):
            summary = await self._compress_history(
                conversation=bounded_conversation,
                current_query=user_message,
                ctx=ctx,
                state=state,
            )
            if summary is not None:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"<conversation_summary>{escape(summary)}"
                            "</conversation_summary>"
                        ),
                    }
                )
            else:
                messages.extend(_conversation_messages(bounded_conversation))
        else:
            messages.extend(_conversation_messages(bounded_conversation))
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _compress_history(
        self,
        *,
        conversation: str,
        current_query: str,
        ctx: AgentContext,
        state: KnowledgeAgentState,
    ) -> str | None:
        state.step += 1
        try:
            result = await self._capabilities.structured(
                "conversation_compression",
                ConversationCompression,
                values={
                    "conversation": conversation,
                    "current_query": current_query,
                    "maximum_characters": (
                        self._conversation_context.max_compressed_characters
                    ),
                },
                ctx=ctx,
                step=state.step,
            )
        except CapabilityExecutionError:
            return None
        state.model_duration_ms += result.duration_ms
        summary = result.value.summary.strip()
        return summary[: self._conversation_context.max_compressed_characters] or None

    async def _stream_model_turn(
        self,
        *,
        messages: Sequence[ModelMessage],
        tools: Sequence[Mapping[str, Any]],
        ctx: AgentContext,
        state: KnowledgeAgentState,
        turn_number: int,
    ) -> AsyncIterator[AgentEvent | StreamCompleted]:
        accumulator = ModelTurnAccumulator()
        citation_buffer = ""
        started_at = perf_counter()
        trace_context = (
            self._tracing.model_turn(
                messages=messages,
                ctx=ctx,
                turn=turn_number,
                tool_round=state.tool_round,
            )
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as generation_trace:
            try:
                async for stream_event in self._transport.stream_turn(
                    messages,
                    tools=tools or None,
                    tool_choice="auto" if tools else None,
                ):
                    accumulator.feed(stream_event)
                    if not isinstance(stream_event, TextDelta):
                        continue
                    if generation_trace is not None:
                        generation_trace.mark_first_token()
                    citation_buffer += stream_event.delta
                    events, citation_buffer = process_citation_buffer(
                        citation_buffer,
                        state.evidence,
                    )
                    for event in events:
                        if isinstance(event, MessageDelta):
                            state.answer_character_count += len(event.text)
                        elif isinstance(event, CitationEvent):
                            state.used_evidence_ids.add(event.evidence_id)
                        yield event
            except LLMTransportError:
                model_duration_ms = duration_ms(started_at)
                if generation_trace is not None:
                    generation_trace.fail(
                        category="transport_error",
                        duration_ms=model_duration_ms,
                    )
                raise

            turn = accumulator.result()
            model_duration_ms = duration_ms(started_at)
            if generation_trace is not None:
                generation_trace.complete(turn=turn, duration_ms=model_duration_ms)
        state.model_duration_ms += model_duration_ms
        if citation_buffer:
            state.answer_character_count += len(citation_buffer)
            yield MessageDelta(text=citation_buffer)
        yield StreamCompleted(turn=turn, duration_ms=model_duration_ms)

    async def _run_tool_round(
        self,
        *,
        calls: list[ToolCall],
        ctx: AgentContext,
        state: KnowledgeAgentState,
    ) -> AsyncIterator[AgentEvent | ToolRoundCompleted]:
        state.tool_round += 1
        remaining_calls = self._max_tool_calls - state.tool_call_count
        accepted_calls: list[tuple[ToolCall, int]] = []
        results_by_id: dict[str, ToolResult] = {}

        for call in calls:
            state.step += 1
            yield ToolStarted(
                call_id=call.call_id,
                name=call.name,
                arguments=call.arguments,
            )
            signature = tool_signature(call)
            if signature in state.executed_tool_signatures:
                results_by_id[call.call_id] = _skipped_tool_result(
                    call,
                    "This exact tool request was already executed in this run.",
                    "duplicate_call",
                )
                continue
            if len(accepted_calls) >= remaining_calls:
                results_by_id[call.call_id] = _skipped_tool_result(
                    call,
                    "The tool-call limit was reached for this run.",
                    "tool_call_limit",
                )
                continue
            state.executed_tool_signatures.add(signature)
            if call.name == "knowledge_search":
                query = call.arguments.get("query")
                if isinstance(query, str) and query.strip():
                    state.search_queries.append(query.strip())
            accepted_calls.append((call, state.step))

        retrieval_query_count = sum(
            call.name == "knowledge_search" for call, _ in accepted_calls
        )
        if retrieval_query_count:
            state.retrieval_round += 1
        accepted = [
            (
                call,
                replace(
                    ctx,
                    trace_step=step,
                    retrieval_round=state.retrieval_round,
                    retrieval_query_count=retrieval_query_count,
                ),
            )
            for call, step in accepted_calls
        ]

        execution_started_at = perf_counter()
        if accepted:
            executed_results = await asyncio.gather(
                *(
                    self._execute_tool(call, execution_context)
                    for call, execution_context in accepted
                )
            )
            state.tool_duration_ms += duration_ms(execution_started_at)
            state.tool_call_count += len(accepted)
            for (call, _), result in zip(accepted, executed_results, strict=True):
                results_by_id[call.call_id] = result

        tool_messages: list[ModelMessage] = []
        for call in calls:
            raw_result = results_by_id[call.call_id]
            result = limit_tool_result(
                raw_result,
                self._max_tool_result_characters,
            )
            for evidence in result.evidence:
                existing = state.evidence.get(evidence.id)
                if existing is None:
                    state.evidence[evidence.id] = evidence
                    yield CitationAvailable(evidence=evidence_reference(evidence))
                elif evidence_score(evidence) > evidence_score(existing):
                    state.evidence[evidence.id] = evidence
            yield ToolCompleted(
                call_id=call.call_id,
                name=call.name,
                error=result.error,
                duration_ms=result_duration(result),
                result_count=result_count(result),
            )
            content = self._model_tool_content(result, state)
            tool_messages.append(
                {
                    "role": "tool",
                    "name": call.name,
                    "tool_call_id": call.call_id,
                    "content": content,
                }
            )
        yield ToolRoundCompleted(messages=tool_messages)

    async def _execute_tool(
        self,
        call: ToolCall,
        ctx: AgentContext,
    ) -> ToolResult:
        if self._tracing is None or call.name == "knowledge_search":
            return await self._registry.execute(call, ctx)
        with self._tracing.tool_execution(
            name=call.name,
            arguments=call.arguments,
        ) as tool_trace:
            result = await self._registry.execute(call, ctx)
            tool_trace.complete(result=result)
            return result

    def _model_tool_content(
        self,
        result: ToolResult,
        state: KnowledgeAgentState,
    ) -> str:
        if result.error:
            content = f"Tool error: {result.error}"
        else:
            content = result.content or "Tool completed without a textual result."
        remaining = self._max_tool_context_characters - state.tool_context_characters
        if remaining <= 0:
            return "Tool result omitted because the agent context limit was reached."
        if len(content) > remaining:
            content = f"{content[: max(1, remaining - 1)].rstrip()}…"
        state.tool_context_characters += len(content)
        return content

    async def _complete_run(
        self,
        *,
        state: KnowledgeAgentState,
        completed_turn: ModelTurn,
        started_at: float,
        run_trace: AgentRunTrace | None,
        turn_number: int,
    ) -> AsyncIterator[AgentEvent]:
        state.completion_status = "completed"
        yield TurnCompleted(turn=turn_number, outcome="final")
        run_duration_ms = duration_ms(started_at)
        if run_trace is not None:
            run_trace.complete(
                answer=completed_turn.text,
                answer_characters=state.answer_character_count,
                turn_count=state.model_turn_count,
                tool_call_count=state.tool_call_count,
                sources_found=len(state.evidence),
                sources_used=len(state.used_evidence_ids),
            )
        yield RunCompleted(
            duration_ms=run_duration_ms,
            model_duration_ms=state.model_duration_ms,
            tool_duration_ms=state.tool_duration_ms,
            tool_call_count=state.tool_call_count,
        )


def _conversation_messages(conversation: str) -> list[ModelMessage]:
    try:
        values = json.loads(conversation)
    except json.JSONDecodeError:
        return []
    if not isinstance(values, list):
        return []
    return [
        {"role": value["role"], "content": value["content"]}
        for value in values
        if isinstance(value, Mapping)
        and value.get("role") in {"user", "assistant"}
        and isinstance(value.get("content"), str)
    ]


def _assistant_tool_message(turn: ModelTurn) -> ModelMessage:
    return {
        "role": "assistant",
        "content": turn.text or None,
        "tool_calls": [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(
                        call.arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }
            for call in turn.tool_calls
        ],
    }


def _skipped_tool_result(
    call: ToolCall,
    error: str,
    outcome: str,
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        content="",
        error=error,
        metadata={"outcome": outcome, "result_count": 0, "duration_ms": 0},
    )


__all__ = ["AgentLoop"]
