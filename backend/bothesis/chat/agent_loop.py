"""Streaming, tool-calling agent loop.

The model stream is forwarded immediately. A small accumulator independently
records each turn so the loop can decide whether to execute tools or finish.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping

from bothesis.agent.models import (
    AgentContext,
    AgentEvent,
    CitationAvailable,
    CitationEvent,
    Evidence,
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

_CITATION_PREFIX = "[[cite:"
_MAX_CITATION_MARKER_LENGTH = 256


@dataclass(slots=True)
class AgentState:
    messages: list[dict[str, Any]]
    evidence: dict[str, Evidence] = field(default_factory=dict)
    turn: int = 0


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
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be at least one")
        self._transport = transport
        self._registry = registry
        self._system_prompt = system_prompt
        self._max_turns = max_turns

    async def run_stream(self, user_message: str, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        """Run one request, forwarding model text before a turn completes."""
        if not user_message.strip():
            yield RunFailed(error="message must not be empty")
            return
        if not ctx.tenant_id or not ctx.user_id:
            yield RunFailed(error="tenant and user context are required")
            return

        state = AgentState(
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ]
        )
        yield RunStarted(conversation_id=ctx.conversation_id)

        for turn_number in range(self._max_turns):
            state.turn = turn_number
            yield TurnStarted(turn=turn_number)
            accumulator = _TurnAccumulator()
            citation_buffer = ""
            try:
                async for stream_event in self._transport.stream_turn(
                    state.messages,
                    tools=self._registry.schemas(),
                ):
                    # The accumulator and frontend forwarding intentionally run
                    # side-by-side so text is not replayed after completion.
                    accumulator.feed(stream_event)
                    if isinstance(stream_event, TextDelta):
                        citation_buffer += stream_event.delta
                        async for event in self._emit_citation_aware_text(
                            citation_buffer, state.evidence
                        ):
                            if isinstance(event, _CitationCarry):
                                citation_buffer = event.value
                            else:
                                yield event
            except LLMTransportError:
                yield RunFailed(error="model stream failed")
                return
            except Exception:
                yield RunFailed(error="model stream failed")
                return

            # Any incomplete marker is visible as ordinary text at end of turn.
            if citation_buffer:
                yield MessageDelta(text=citation_buffer)

            completed_turn = accumulator.result()
            if completed_turn.tool_calls:
                state.messages.append(_assistant_tool_message(completed_turn))
                for tool_call in completed_turn.tool_calls:
                    yield ToolStarted(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                    )
                    result = await self._registry.execute(tool_call, ctx)
                    result = _with_call_id(result, tool_call.call_id)
                    for evidence in result.evidence:
                        state.evidence[evidence.id] = evidence
                        yield CitationAvailable(evidence=evidence)
                    state.messages.append(_tool_result_message(result))
                    yield ToolCompleted(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        error=result.error,
                    )
                yield TurnCompleted(turn=turn_number, outcome="tool")
                continue

            yield TurnCompleted(turn=turn_number, outcome="final")
            yield RunCompleted()
            return

        yield RunFailed(error="max_turns exceeded")

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
    )
