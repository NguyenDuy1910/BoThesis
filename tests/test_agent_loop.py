from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import (
    AgentContext,
    CitationAvailable,
    CitationEvent,
    ConversationMessage,
    Evidence,
    MessageDelta,
    RunCompleted,
    RunFailed,
    RunStarted,
    TextDelta,
    ToolResult,
    ToolStarted,
    TurnCompleted,
    TurnDone,
    TurnStarted,
)
from bothesis.agent.tools import AgentTool, ToolRegistry
from bothesis.agent.transports.base import (
    ChatMessage,
    LLMResponse,
    LLMTransport,
    LLMTransportError,
)
from bothesis.chat.agent_loop import AgentLoop

CONTEXT = AgentContext(
    user_id="user-1",
    tenant_id="tenant-1",
    roles=["employee"],
)


def completion(payload: object) -> LLMResponse:
    return LLMResponse(
        id="response-1",
        model="openai/gpt-5.4-mini",
        content=json.dumps(payload),
        finish_reason="stop",
        usage={
            "prompt_tokens": 20,
            "cached_prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 25,
        },
    )


class ScriptedTransport(LLMTransport):
    def __init__(
        self,
        completions: list[LLMResponse],
        streams: list[list[TextDelta | TurnDone]],
    ) -> None:
        self.completions = completions
        self.streams = streams
        self.complete_requests: list[list[dict[str, Any]]] = []
        self.stream_requests: list[list[dict[str, Any]]] = []
        self.finished_streams = 0

    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> LLMResponse:
        self.complete_requests.append([dict(message) for message in messages])
        if not self.completions:
            raise AssertionError("unexpected structured capability call")
        return self.completions.pop(0)

    async def stream_turn(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[TextDelta | TurnDone]:
        self.stream_requests.append([dict(message) for message in messages])
        if not self.streams:
            raise AssertionError("unexpected streaming capability call")
        for event in self.streams.pop(0):
            yield event
        self.finished_streams += 1


class SearchTool(AgentTool):
    name = "knowledge_search"
    description = "Search enterprise documents."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }

    def __init__(
        self,
        *,
        empty_queries: set[str] | None = None,
        delay: float = 0,
    ) -> None:
        self.empty_queries = empty_queries or set()
        self.delay = delay
        self.calls: list[tuple[str, AgentContext]] = []
        self.active_calls = 0
        self.max_active_calls = 0

    async def execute(
        self,
        arguments: dict[str, Any],
        ctx: AgentContext,
    ) -> ToolResult:
        query = str(arguments["query"])
        self.calls.append((query, ctx))
        call_position = len(self.calls)
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        if self.delay:
            await asyncio.sleep(self.delay)
        self.active_calls -= 1
        if query in self.empty_queries:
            return ToolResult(
                call_id="",
                content="No matching enterprise documents were found.",
                metadata={
                    "outcome": "empty",
                    "result_count": 0,
                    "duration_ms": 1,
                },
            )
        evidence_id = f"ev-{call_position}"
        evidence = Evidence(
            id=evidence_id,
            document_id=f"doc-{call_position}",
            title=f"Source for {query}",
            content=f"Evidence about {query}.",
            source="confluence",
            uri=f"https://knowledge.example/{evidence_id}",
        )
        return ToolResult(
            call_id="",
            content=f"[{evidence_id}] {evidence.content}",
            evidence=[evidence],
            metadata={
                "outcome": "success",
                "result_count": 1,
                "duration_ms": 1,
            },
        )


def make_loop(
    completions: list[LLMResponse],
    stream: list[TextDelta | TurnDone],
    *,
    tool: SearchTool | None = None,
    max_retrieval_rounds: int = 2,
    max_tool_calls: int = 6,
    max_capability_calls: int = 8,
) -> tuple[AgentLoop, ScriptedTransport, SearchTool]:
    search_tool = tool or SearchTool()
    registry = ToolRegistry()
    registry.register(search_tool)
    transport = ScriptedTransport(completions, [stream])
    loop = AgentLoop(
        transport,
        registry,
        max_retrieval_rounds=max_retrieval_rounds,
        max_tool_calls=max_tool_calls,
        max_capability_calls=max_capability_calls,
    )
    return loop, transport, search_tool


async def collect(
    loop: AgentLoop,
    message: str = "What is the leave policy?",
    context: AgentContext = CONTEXT,
) -> list[Any]:
    return [event async for event in loop.run_stream(message, context)]


@pytest.mark.asyncio
async def test_simple_request_rewrites_retrieves_and_streams_grounded_answer() -> None:
    loop, transport, tool = make_loop(
        [completion({"query": "annual leave policy"})],
        [
            TextDelta("Employees receive leave [[cite:ev-1]]."),
            TurnDone("stop", model="openai/gpt-5.4-mini"),
        ],
    )

    events = await collect(loop)

    assert tool.calls[0][0] == "annual leave policy"
    assert len(transport.complete_requests) == 1
    assert "<task>\nRewrite" in transport.complete_requests[0][0]["content"]
    assert any(isinstance(event, CitationAvailable) for event in events)
    assert any(isinstance(event, CitationEvent) for event in events)
    assert isinstance(events[0], RunStarted)
    assert isinstance(events[-1], RunCompleted)
    assert [event.outcome for event in events if isinstance(event, TurnCompleted)] == [
        "tool",
        "final",
    ]


@pytest.mark.asyncio
async def test_simple_request_skips_decomposition_evaluation_and_synthesis() -> None:
    loop, transport, _ = make_loop(
        [completion({"query": "annual leave policy"})],
        [TextDelta("Grounded answer."), TurnDone("stop")],
    )

    events = await collect(loop)

    assert isinstance(events[-1], RunCompleted)
    assert len(transport.complete_requests) == 1
    assert "Write the user-facing answer" in transport.stream_requests[0][0]["content"]


@pytest.mark.asyncio
async def test_complex_request_decomposes_and_retrieves_queries_in_parallel() -> None:
    tool = SearchTool(delay=0.01)
    loop, transport, _ = make_loop(
        [
            completion({"query": "Compare annual leave and sick leave policies"}),
            completion(
                {
                    "queries": [
                        "annual leave policy",
                        "sick leave policy",
                    ]
                }
            ),
            completion(
                {
                    "sufficient": True,
                    "covered": ["annual leave", "sick leave"],
                    "missing": [],
                    "conflicts": [],
                    "requires_additional_retrieval": False,
                }
            ),
            completion(
                {
                    "facts": [
                        {"claim": "Annual leave fact", "evidence_ids": ["ev-1"]},
                        {"claim": "Sick leave fact", "evidence_ids": ["ev-2"]},
                    ],
                    "conflicts": [],
                    "missing": [],
                }
            ),
        ],
        [
            *(
                TextDelta(character)
                for character in "Comparison [[cite:ev-1]][[cite:ev-2]]."
            ),
            TurnDone("stop"),
        ],
        tool=tool,
    )

    events = await collect(loop, "Compare annual leave and sick leave policies")

    assert [query for query, _ in tool.calls] == [
        "annual leave policy",
        "sick leave policy",
    ]
    assert tool.max_active_calls == 2
    assert len(transport.complete_requests) == 4
    assert sum(isinstance(event, ToolStarted) for event in events) == 2
    citation_ids = [
        event.evidence_id for event in events if isinstance(event, CitationEvent)
    ]
    assert citation_ids == ["ev-1", "ev-2"]
    visible_text = "".join(
        event.text for event in events if isinstance(event, MessageDelta)
    )
    assert "[[cite:" not in visible_text
    assert events[-1].tool_call_count == 2


@pytest.mark.asyncio
async def test_missing_evidence_refines_without_repeating_previous_queries() -> None:
    loop, transport, tool = make_loop(
        [
            completion({"query": "Compare annual and sick leave"}),
            completion({"queries": ["annual leave policy", "sick leave policy"]}),
            completion(
                {
                    "sufficient": False,
                    "covered": ["annual leave"],
                    "missing": ["sick leave eligibility"],
                    "conflicts": [],
                    "requires_additional_retrieval": True,
                }
            ),
            completion(
                {
                    "queries": [
                        "annual leave policy",
                        "sick leave eligibility rules",
                    ]
                }
            ),
            completion(
                {
                    "sufficient": True,
                    "covered": ["annual leave", "sick leave eligibility"],
                    "missing": [],
                    "conflicts": [],
                    "requires_additional_retrieval": False,
                }
            ),
            completion(
                {
                    "facts": [
                        {"claim": "Leave facts", "evidence_ids": ["ev-1", "ev-3"]}
                    ],
                    "conflicts": [],
                    "missing": [],
                }
            ),
        ],
        [TextDelta("Grounded result [[cite:ev-3]]."), TurnDone("stop")],
    )

    events = await collect(loop, "Compare annual and sick leave")

    assert [query for query, _ in tool.calls] == [
        "annual leave policy",
        "sick leave policy",
        "sick leave eligibility rules",
    ]
    assert len(transport.complete_requests) == 6
    assert [event.turn for event in events if isinstance(event, TurnStarted)] == [
        0,
        1,
        2,
    ]


@pytest.mark.asyncio
async def test_empty_results_can_refine_once_and_still_answer_safely() -> None:
    tool = SearchTool(empty_queries={"unknown policy", "policy owner"})
    loop, _, _ = make_loop(
        [
            completion({"query": "unknown policy"}),
            completion(
                {
                    "sufficient": False,
                    "covered": [],
                    "missing": ["policy owner"],
                    "conflicts": [],
                    "requires_additional_retrieval": True,
                }
            ),
            completion({"queries": ["policy owner"]}),
            completion(
                {
                    "sufficient": False,
                    "covered": [],
                    "missing": ["policy owner"],
                    "conflicts": [],
                    "requires_additional_retrieval": False,
                }
            ),
        ],
        [TextDelta("The available sources do not establish this."), TurnDone("stop")],
        tool=tool,
    )

    events = await collect(loop, "unknown policy")

    assert [query for query, _ in tool.calls] == ["unknown policy", "policy owner"]
    assert isinstance(events[-1], RunCompleted)


@pytest.mark.asyncio
async def test_capability_and_tool_limits_bound_a_complex_run() -> None:
    loop, transport, tool = make_loop(
        [completion({"query": "Compare leave and holidays"})],
        [TextDelta("Bounded answer."), TurnDone("stop")],
        max_tool_calls=1,
        max_capability_calls=2,
    )

    events = await collect(loop, "Compare leave and holidays")

    assert len(transport.complete_requests) == 1
    assert len(tool.calls) == 1
    assert isinstance(events[-1], RunCompleted)
    assert events[-1].tool_call_count == 1


@pytest.mark.asyncio
async def test_malformed_rewrite_falls_back_to_original_query() -> None:
    malformed = LLMResponse(
        id="bad",
        model="openai/gpt-5.4-mini",
        content="not-json",
        finish_reason="stop",
    )
    loop, _, tool = make_loop(
        [malformed],
        [TextDelta("Answer."), TurnDone("stop")],
    )

    events = await collect(loop)

    assert tool.calls[0][0] == "What is the leave policy?"
    assert isinstance(events[-1], RunCompleted)


@pytest.mark.asyncio
async def test_ambiguous_request_asks_for_clarification_without_retrieval() -> None:
    loop, transport, tool = make_loop(
        [],
        [TextDelta("Which policy do you mean?"), TurnDone("stop")],
    )

    events = await collect(loop, "What about that?")

    assert tool.calls == []
    assert transport.complete_requests == []
    assert "Ask one concise clarification" in transport.stream_requests[0][0]["content"]
    assert isinstance(events[-1], RunCompleted)


@pytest.mark.asyncio
async def test_final_answer_is_yielded_before_stream_completion() -> None:
    loop, transport, _ = make_loop(
        [completion({"query": "annual leave policy"})],
        [TextDelta("first token"), TurnDone("stop")],
    )
    stream = loop.run_stream("What is the leave policy?", CONTEXT)

    while True:
        event = await anext(stream)
        if isinstance(event, MessageDelta):
            break

    assert event == MessageDelta("first token")
    assert transport.finished_streams == 0


@pytest.mark.asyncio
async def test_split_citation_marker_is_reassembled() -> None:
    loop, _, _ = make_loop(
        [completion({"query": "annual leave policy"})],
        [
            TextDelta("policy [[cite:ev"),
            TextDelta("-1]] applies"),
            TurnDone("stop"),
        ],
    )

    events = await collect(loop)
    relevant = [
        event for event in events if isinstance(event, (MessageDelta, CitationEvent))
    ]

    assert relevant[0] == MessageDelta("policy ")
    assert relevant[1] == CitationEvent(
        evidence_id="ev-1",
        title="Source for annual leave policy",
        uri="https://knowledge.example/ev-1",
    )
    assert relevant[2] == MessageDelta(" applies")


@pytest.mark.asyncio
async def test_history_is_runtime_input_at_the_end_of_rewrite_prompt() -> None:
    loop, transport, _ = make_loop(
        [completion({"query": "annual leave follow-up"})],
        [TextDelta("Answer."), TurnDone("stop")],
    )
    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=[],
        history=(
            ConversationMessage(role="user", content="Earlier question"),
            ConversationMessage(role="assistant", content="Earlier answer"),
        ),
    )

    events = await collect(loop, "What about annual leave?", context)
    prompt = transport.complete_requests[0][0]["content"]

    assert isinstance(events[-1], RunCompleted)
    assert prompt.index("<instructions>") < prompt.index("<input>")
    assert "Earlier question" in prompt
    assert prompt.rstrip().endswith("</input>")


@pytest.mark.asyncio
async def test_transport_failure_returns_retryable_run_failure() -> None:
    class FailingTransport(ScriptedTransport):
        async def stream_turn(self, *args: Any, **kwargs: Any) -> Any:
            raise LLMTransportError("unavailable")
            yield  # pragma: no cover

    registry = ToolRegistry()
    registry.register(SearchTool())
    transport = FailingTransport(
        [completion({"query": "annual leave policy"})],
        [],
    )
    loop = AgentLoop(transport, registry)

    events = await collect(loop)

    assert isinstance(events[-1], RunFailed)
    assert events[-1].error == "model response failed"
