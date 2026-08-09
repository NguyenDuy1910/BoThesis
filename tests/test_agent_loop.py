from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
import sys
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import (
    AgentContext,
    CitationAvailable,
    CitationEvent,
    Evidence,
    MessageDelta,
    RunCompleted,
    RunFailed,
    RunStarted,
    TextDelta,
    ToolCallDelta,
    ToolCompleted,
    ToolResult,
    ToolStarted,
    TurnCompleted,
    TurnDone,
    TurnStarted,
)
from bothesis.agent.tools import AgentTool, ToolRegistry
from bothesis.agent.transports.base import ChatMessage, LLMResponse, LLMTransport
from bothesis.chat.agent_loop import AgentLoop


EVIDENCE = Evidence(
    id="ev_123",
    document_id="doc_leave_policy",
    title="Employee Leave Policy",
    content="Employees receive 20 days of annual leave.",
    page="4",
    uri="https://knowledge.example/leave-policy",
)
CONTEXT = AgentContext(user_id="user-1", tenant_id="tenant-1", roles=["employee"])


class ScriptedTransport(LLMTransport):
    def __init__(self, turns: list[list[TextDelta | ToolCallDelta | TurnDone]]) -> None:
        self.turns = turns
        self.requests: list[list[dict[str, Any]]] = []
        self.finished_streams = 0

    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> LLMResponse:
        raise AssertionError("the agent loop must use stream_turn")

    async def stream_turn(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[TextDelta | ToolCallDelta | TurnDone]:
        self.requests.append([dict(message) for message in messages])
        turn = self.turns.pop(0)
        for event in turn:
            yield event
        self.finished_streams += 1


class SearchTool(AgentTool):
    name = "knowledge_search"
    description = "Search enterprise documents."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self, *, result: ToolResult | None = None, raises: bool = False) -> None:
        self._result = result or ToolResult(call_id="", content="Leave policy evidence", evidence=[EVIDENCE])
        self._raises = raises
        self.calls: list[tuple[dict[str, Any], AgentContext]] = []

    async def execute(self, arguments: dict[str, Any], ctx: AgentContext) -> ToolResult:
        self.calls.append((arguments, ctx))
        if self._raises:
            raise RuntimeError("retrieval unavailable")
        return self._result


def make_loop(
    turns: list[list[TextDelta | ToolCallDelta | TurnDone]],
    *,
    tool: AgentTool | None = None,
    max_turns: int = 6,
) -> tuple[AgentLoop, ScriptedTransport]:
    registry = ToolRegistry()
    registry.register(tool or SearchTool())
    transport = ScriptedTransport(turns)
    return AgentLoop(transport, registry, "Use enterprise evidence.", max_turns=max_turns), transport


async def collect(loop: AgentLoop) -> list[Any]:
    return [event async for event in loop.run_stream("What is the leave policy?", CONTEXT)]


@pytest.mark.asyncio
async def test_direct_final_answer_streams_and_completes() -> None:
    loop, _ = make_loop([[TextDelta("Hello "), TextDelta("there"), TurnDone("stop")]])

    events = await collect(loop)

    assert [type(event) for event in events] == [
        RunStarted,
        TurnStarted,
        MessageDelta,
        MessageDelta,
        TurnCompleted,
        RunCompleted,
    ]
    assert [event.text for event in events if isinstance(event, MessageDelta)] == ["Hello ", "there"]
    assert events[-2].outcome == "final"


@pytest.mark.asyncio
async def test_one_tool_call_then_grounded_answer() -> None:
    loop, _ = make_loop(
        [
            [
                ToolCallDelta("call-1", "knowledge_search", '{"query":"leave policy"}'),
                TurnDone("tool_calls"),
            ],
            [TextDelta("Employees receive leave [[cite:ev_123]]."), TurnDone("stop")],
        ]
    )

    events = await collect(loop)

    assert any(isinstance(event, ToolStarted) for event in events)
    assert any(isinstance(event, ToolCompleted) for event in events)
    assert any(isinstance(event, CitationAvailable) and event.evidence == EVIDENCE for event in events)
    assert any(isinstance(event, CitationEvent) and event.evidence_id == EVIDENCE.id for event in events)
    assert "Employees receive leave " in [event.text for event in events if isinstance(event, MessageDelta)]
    assert [event.outcome for event in events if isinstance(event, TurnCompleted)] == ["tool", "final"]


@pytest.mark.asyncio
async def test_multiple_tool_turns_increment_the_turn_counter() -> None:
    tool_turn = [ToolCallDelta("call-1", "knowledge_search", '{"query":"leave"}'), TurnDone("tool_calls")]
    loop, _ = make_loop([tool_turn, tool_turn, [TextDelta("Done."), TurnDone("stop")]])

    events = await collect(loop)

    assert [event.turn for event in events if isinstance(event, TurnStarted)] == [0, 1, 2]
    assert [event.outcome for event in events if isinstance(event, TurnCompleted)] == ["tool", "tool", "final"]


@pytest.mark.asyncio
async def test_text_is_yielded_before_its_turn_completes() -> None:
    loop, transport = make_loop([[TextDelta("first token"), TurnDone("stop")]])
    stream = loop.run_stream("What is the leave policy?", CONTEXT)

    assert isinstance(await anext(stream), RunStarted)
    assert isinstance(await anext(stream), TurnStarted)
    delta = await anext(stream)

    assert delta == MessageDelta("first token")
    # The transport remains paused at its ``yield TextDelta``. A buffered loop
    # would have consumed TurnDone and incremented this counter first.
    assert transport.finished_streams == 0


@pytest.mark.asyncio
async def test_split_citation_marker_is_reassembled_without_buffering_text() -> None:
    loop, _ = make_loop(
        [
            [
                ToolCallDelta("call-1", "knowledge_search", '{"query":"leave"}'),
                TurnDone("tool_calls"),
            ],
            [TextDelta("policy [[cite:ev"), TextDelta("_123]] applies"), TurnDone("stop")],
        ]
    )

    events = await collect(loop)

    relevant = [event for event in events if isinstance(event, (MessageDelta, CitationEvent))]
    assert isinstance(relevant[0], MessageDelta) and relevant[0].text == "policy "
    assert isinstance(relevant[1], CitationEvent) and relevant[1].evidence_id == "ev_123"
    assert isinstance(relevant[2], MessageDelta) and relevant[2].text == " applies"


@pytest.mark.asyncio
async def test_unknown_citation_id_remains_visible_text() -> None:
    loop, _ = make_loop([[TextDelta("No source [[cite:ev_unknown]] found"), TurnDone("stop")]])

    events = await collect(loop)

    assert not any(isinstance(event, CitationEvent) for event in events)
    assert "".join(event.text for event in events if isinstance(event, MessageDelta)) == (
        "No source [[cite:ev_unknown]] found"
    )


@pytest.mark.asyncio
async def test_max_turns_emits_failure() -> None:
    tool_turn = [ToolCallDelta("call-1", "knowledge_search", '{"query":"leave"}'), TurnDone("tool_calls")]
    loop, _ = make_loop([tool_turn, tool_turn], max_turns=2)

    events = await collect(loop)

    assert isinstance(events[-1], RunFailed)
    assert events[-1].error == "max_turns exceeded"


@pytest.mark.asyncio
async def test_tool_failure_is_observed_by_the_next_model_turn() -> None:
    loop, transport = make_loop(
        [
            [
                ToolCallDelta("call-1", "knowledge_search", '{"query":"leave"}'),
                TurnDone("tool_calls"),
            ],
            [TextDelta("I could not retrieve the policy."), TurnDone("stop")],
        ],
        tool=SearchTool(raises=True),
    )

    events = await collect(loop)

    completed = next(event for event in events if isinstance(event, ToolCompleted))
    assert completed.error == "Tool execution failed: knowledge_search"
    assert transport.requests[1][-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "Tool error: Tool execution failed: knowledge_search",
    }
