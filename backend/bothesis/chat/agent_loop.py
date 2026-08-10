"""Streaming, tool-calling agent loop.

The model stream is forwarded immediately. A small accumulator independently
records each turn so the loop can decide whether to execute tools or finish.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from bothesis.agent.models import (
    AgentContext,
    AgentEvent,
    CitationAvailable,
    CitationEvent,
    ConversationMessage,
    Evidence,
    EvidenceReference,
    MessageDelta,
    ModelTurn,
    RunCompleted,
    RunFailed,
    RunStarted,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolCompleted,
    ToolResult,
    ToolStarted,
    TurnCompleted,
    TurnDone,
    TurnStarted,
)
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.transports.base import LLMTransport, LLMTransportError
from bothesis.observability import AgentRunTrace, LangfuseTracing

_CITATION_PREFIX = "[[cite:"
_MAX_CITATION_MARKER_LENGTH = 256


@dataclass(slots=True)
class AgentState:
    messages: list[dict[str, Any]]
    evidence: dict[str, Evidence] = field(default_factory=dict)
    executed_tool_requests: set[str] = field(default_factory=set)
    turn: int = 0
    tool_call_count: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    answer_character_count: int = 0
    used_evidence_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _PendingToolCall:
    name: str = ""
    arguments: str = ""


class _TurnAccumulator:
    """Collects the small amount of state needed after a streamed turn."""

    def __init__(self) -> None:
        self._text: list[str] = []
        self._tool_calls: dict[str, _PendingToolCall] = {}
        self._tool_order: list[str] = []
        self._finish_reason: str | None = None
        self._model: str | None = None
        self._usage: dict[str, int] = {}

    def feed(self, event: TextDelta | ToolCallDelta | TurnDone) -> None:
        if isinstance(event, TextDelta):
            self._text.append(event.delta)
            return
        if isinstance(event, ToolCallDelta):
            pending = self._get_or_create(event.call_id)
            if event.name:
                pending.name += event.name
            pending.arguments += event.arguments
            return
        self._finish_reason = event.finish_reason
        self._model = event.model
        self._usage = event.usage
        for raw_call in event.tool_calls:
            self._merge_complete_tool_call(raw_call)

    def result(self) -> ModelTurn:
        calls: list[ToolCall] = []
        for call_id in self._tool_order:
            pending = self._tool_calls[call_id]
            calls.append(
                ToolCall(
                    call_id=call_id,
                    name=pending.name,
                    arguments=_decode_tool_arguments(pending.arguments),
                )
            )
        return ModelTurn(
            text="".join(self._text),
            tool_calls=calls,
            finish_reason=self._finish_reason,
            model=self._model,
            usage=self._usage,
        )

    def _get_or_create(self, call_id: str) -> _PendingToolCall:
        if call_id not in self._tool_calls:
            self._tool_calls[call_id] = _PendingToolCall()
            self._tool_order.append(call_id)
        return self._tool_calls[call_id]

    def _merge_complete_tool_call(self, raw_call: Mapping[str, Any]) -> None:
        call_id = str(raw_call.get("id") or raw_call.get("call_id") or "")
        if not call_id:
            return
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            function = raw_call
        raw_name = function.get("name")
        raw_arguments = function.get("arguments", raw_call.get("arguments", ""))
        arguments = raw_arguments if isinstance(raw_arguments, str) else json.dumps(raw_arguments)
        pending = self._get_or_create(call_id)
        if isinstance(raw_name, str):
            pending.name = raw_name
        pending.arguments = arguments


def _decode_tool_arguments(arguments: str) -> dict[str, Any]:
    if not arguments:
        return {}
    try:
        decoded = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _parse_citations(
    buffer: str, known_evidence_ids: set[str]
) -> tuple[str, list[str], str]:
    """Consume one citation marker while retaining only a possible partial one.

    The returned text never includes a known citation marker; unknown markers
    are retained as visible text. Callers invoke this repeatedly until the
    remaining buffer is either empty or an unfinished marker.
    """

    marker_start = buffer.find("[[")
    if marker_start < 0:
        return buffer, [], ""

    before = buffer[:marker_start]
    candidate = buffer[marker_start:]
    marker_end = candidate.find("]]")
    if marker_end < 0:
        if (
            _CITATION_PREFIX.startswith(candidate)
            or candidate.startswith(_CITATION_PREFIX)
        ) and len(candidate) <= _MAX_CITATION_MARKER_LENGTH:
            return before, [], candidate
        return before + candidate, [], ""

    marker = candidate[: marker_end + 2]
    remainder = candidate[marker_end + 2 :]
    if not marker.startswith(_CITATION_PREFIX) or not marker.endswith("]]"):
        return before + marker, [], remainder
    evidence_id = marker[len(_CITATION_PREFIX) : -2]
    if not evidence_id or not all(char.isalnum() or char in "_.:-" for char in evidence_id):
        return before + marker, [], remainder
    if evidence_id not in known_evidence_ids:
        return before + marker, [], remainder
    return before, [evidence_id], remainder


class AgentLoop:
    def __init__(
        self,
        transport: LLMTransport,
        registry: ToolRegistry,
        system_prompt: str,
        max_turns: int = 6,
        max_tool_calls: int = 3,
        max_history_messages: int = 8,
        max_history_characters: int = 8_000,
        max_tool_result_characters: int = 10_000,
        max_user_message_characters: int = 4_000,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be at least one")
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least one")
        if min(
            max_history_messages,
            max_history_characters,
            max_tool_result_characters,
            max_user_message_characters,
        ) < 1:
            raise ValueError("agent limits must be at least one")
        self._transport = transport
        self._registry = registry
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._max_tool_calls = max_tool_calls
        self._max_history_messages = max_history_messages
        self._max_history_characters = max_history_characters
        self._max_tool_result_characters = max_tool_result_characters
        self._max_user_message_characters = max_user_message_characters
        self._tracing = tracing

    async def run_stream(self, user_message: str, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        """Run one request, forwarding model text before a turn completes."""
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
            async for event in self._run_validated_stream(normalized_message, ctx, run_trace):
                yield event

    async def _run_validated_stream(
        self,
        normalized_message: str,
        ctx: AgentContext,
        run_trace: AgentRunTrace | None,
    ) -> AsyncIterator[AgentEvent]:
        """Execute a validated request inside its optional trace context."""

        started_at = perf_counter()
        state = AgentState(
            messages=[
                {"role": "system", "content": self._system_prompt},
                *self._history_messages(ctx.history),
                {"role": "user", "content": normalized_message},
            ]
        )
        yield RunStarted(
            conversation_id=ctx.conversation_id,
            request_id=ctx.request_id,
        )

        for turn_number in range(self._max_turns):
            state.turn = turn_number
            yield TurnStarted(turn=turn_number)
            accumulator = _TurnAccumulator()
            citation_buffer = ""
            model_started_at = perf_counter()
            tool_schemas = self._registry.schemas()
            generation_context = (
                self._tracing.generation(
                    turn=turn_number,
                    messages=state.messages,
                    tool_count=len(tool_schemas),
                )
                if self._tracing is not None
                else nullcontext(None)
            )
            try:
                with generation_context as generation_trace:
                    async for stream_event in self._transport.stream_turn(
                        state.messages,
                        tools=tool_schemas,
                    ):
                        # The accumulator and frontend forwarding intentionally run
                        # side-by-side so text is not replayed after completion.
                        accumulator.feed(stream_event)
                        if isinstance(stream_event, TextDelta):
                            if generation_trace is not None:
                                generation_trace.mark_first_token()
                            citation_buffer += stream_event.delta
                            async for event in self._emit_citation_aware_text(
                                citation_buffer, state.evidence
                            ):
                                if isinstance(event, _CitationCarry):
                                    citation_buffer = event.value
                                else:
                                    if isinstance(event, MessageDelta):
                                        state.answer_character_count += len(event.text)
                                    elif isinstance(event, CitationEvent):
                                        state.used_evidence_ids.add(event.evidence_id)
                                    yield event
                    completed_turn = accumulator.result()
                    if generation_trace is not None:
                        generation_trace.complete(
                            model=completed_turn.model,
                            usage=completed_turn.usage,
                            finish_reason=completed_turn.finish_reason,
                            text_characters=len(completed_turn.text),
                            tool_call_count=len(completed_turn.tool_calls),
                        )
            except LLMTransportError:
                state.model_duration_ms += _duration_ms(model_started_at)
                if run_trace is not None:
                    run_trace.fail(stage="model")
                yield RunFailed(error="model stream failed")
                return
            except Exception:
                state.model_duration_ms += _duration_ms(model_started_at)
                if run_trace is not None:
                    run_trace.fail(stage="model")
                yield RunFailed(error="model stream failed")
                return
            state.model_duration_ms += _duration_ms(model_started_at)

            # Any incomplete marker is visible as ordinary text at end of turn.
            if citation_buffer:
                state.answer_character_count += len(citation_buffer)
                yield MessageDelta(text=citation_buffer)

            if completed_turn.tool_calls:
                state.messages.append(_assistant_tool_message(completed_turn))
                for tool_call in completed_turn.tool_calls:
                    yield ToolStarted(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                    )
                    tool_started_at = perf_counter()
                    signature = _tool_request_signature(tool_call)
                    if state.tool_call_count >= self._max_tool_calls:
                        result = ToolResult(
                            call_id=tool_call.call_id,
                            content="",
                            error="Tool-call limit reached for this run.",
                            metadata={
                                "outcome": "tool_limit",
                                "result_count": 0,
                                "duration_ms": 0,
                            },
                        )
                    elif signature in state.executed_tool_requests:
                        result = ToolResult(
                            call_id=tool_call.call_id,
                            content="",
                            error="Duplicate tool request skipped for this run.",
                            metadata={
                                "outcome": "duplicate",
                                "result_count": 0,
                                "duration_ms": 0,
                            },
                        )
                    else:
                        state.executed_tool_requests.add(signature)
                        state.tool_call_count += 1
                        result = await self._registry.execute(tool_call, ctx)
                        result = _with_call_id(result, tool_call.call_id)
                    duration_ms = _duration_ms(tool_started_at)
                    state.tool_duration_ms += duration_ms
                    result = _limit_tool_result(
                        result,
                        self._max_tool_result_characters,
                    )
                    for evidence in result.evidence:
                        state.evidence[evidence.id] = evidence
                        yield CitationAvailable(evidence=_evidence_reference(evidence))
                    state.messages.append(_tool_result_message(result))
                    yield ToolCompleted(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        error=result.error,
                        duration_ms=duration_ms,
                        result_count=_result_count(result),
                    )
                yield TurnCompleted(turn=turn_number, outcome="tool")
                continue

            yield TurnCompleted(turn=turn_number, outcome="final")
            run_duration_ms = _duration_ms(started_at)
            if run_trace is not None:
                run_trace.complete(
                    answer_characters=state.answer_character_count,
                    turn_count=turn_number + 1,
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
            return

        if run_trace is not None:
            run_trace.fail(stage="turn_limit")
        yield RunFailed(error="max_turns exceeded")

    def _history_messages(
        self,
        history: tuple[ConversationMessage, ...],
    ) -> list[dict[str, str]]:
        remaining_characters = self._max_history_characters
        bounded_messages: list[dict[str, str]] = []
        for message in reversed(history[-self._max_history_messages :]):
            content = message.content.strip()
            if not content or remaining_characters <= 0:
                continue
            content = content[-remaining_characters:]
            bounded_messages.append({"role": message.role, "content": content})
            remaining_characters -= len(content)
        return list(reversed(bounded_messages))

    async def _emit_citation_aware_text(
        self, buffer: str, evidence: Mapping[str, Evidence]
    ) -> AsyncIterator[MessageDelta | CitationEvent | _CitationCarry]:
        remaining = buffer
        known_ids = set(evidence)
        while remaining:
            text, evidence_ids, next_remaining = _parse_citations(remaining, known_ids)
            if text:
                yield MessageDelta(text=text)
            for evidence_id in evidence_ids:
                item = evidence[evidence_id]
                yield CitationEvent(
                    evidence_id=evidence_id,
                    title=item.title,
                    page=item.page,
                    uri=item.uri,
                )
            if next_remaining == remaining:
                yield _CitationCarry(next_remaining)
                return
            remaining = next_remaining
        yield _CitationCarry("")


@dataclass(frozen=True, slots=True)
class _CitationCarry:
    value: str


def _assistant_tool_message(turn: ModelTurn) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": turn.text or None,
        "tool_calls": [
            {
                "id": tool_call.call_id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            }
            for tool_call in turn.tool_calls
        ],
    }


def _tool_result_message(result: ToolResult) -> dict[str, Any]:
    observation = result.content
    if result.error:
        observation = f"Tool error: {result.error}"
    return {"role": "tool", "tool_call_id": result.call_id, "content": observation}


def _with_call_id(result: ToolResult, call_id: str) -> ToolResult:
    """Tool implementations need not know provider-generated call IDs."""
    if result.call_id == call_id:
        return result
    return ToolResult(
        call_id=call_id,
        content=result.content,
        evidence=result.evidence,
        error=result.error,
        metadata=result.metadata,
    )


def _tool_request_signature(tool_call: ToolCall) -> str:
    arguments = dict(tool_call.arguments)
    query = arguments.get("query")
    if tool_call.name == "knowledge_search" and isinstance(query, str):
        arguments["query"] = query.strip().casefold()
    return f"{tool_call.name}:{json.dumps(arguments, sort_keys=True)}"


def _limit_tool_result(result: ToolResult, max_characters: int) -> ToolResult:
    if len(result.content) <= max_characters:
        return result
    truncated_content = f"{result.content[: max_characters - 1].rstrip()}…"
    return ToolResult(
        call_id=result.call_id,
        content=truncated_content,
        evidence=result.evidence,
        error=result.error,
        metadata=result.metadata,
    )


def _result_count(result: ToolResult) -> int | None:
    value = result.metadata.get("result_count")
    return value if isinstance(value, int) else None


def _duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1_000)


def _evidence_reference(evidence: Evidence) -> EvidenceReference:
    return EvidenceReference(
        id=evidence.id,
        document_id=evidence.document_id,
        title=evidence.title,
        page=evidence.page,
        section=evidence.section,
        uri=evidence.uri,
        source=evidence.source,
        relevance_score=evidence.relevance_score,
    )
