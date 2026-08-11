from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import (
    AgentContext,
    CitationEvent,
    CommentaryDelta,
    ConversationMessage,
    Evidence,
    ExecutionMode,
    FinalAnswerDelta,
    IntermediateFindingDelta,
    InterleavedToolCompleted,
    InterleavedToolStarted,
    RunCompleted,
    TextDelta,
    ToolResult,
    TurnDone,
)
from bothesis.agent.tools import AgentTool, ToolRegistry
from bothesis.agent.transports.base import ChatMessage, LLMResponse, LLMTransport
from bothesis.chat.agent_loop import AgentLoop

CONTEXT = AgentContext(user_id="user-1", tenant_id="tenant-1", roles=["employee"])


def response(payload: object) -> LLMResponse:
    return LLMResponse(
        id="response",
        model="test-model",
        content=json.dumps(payload),
        finish_reason="stop",
    )


def plan(*steps: dict[str, object], commentary: str | None = "I’ll check the relevant sources.") -> LLMResponse:
    return response(
        {
            "mode": "planned",
            "requires_knowledge_retrieval": True,
            "commentary": commentary,
            "steps": list(steps),
        }
    )


def direct() -> LLMResponse:
    return response(
        {
            "mode": "direct",
            "requires_knowledge_retrieval": False,
            "commentary": None,
            "steps": [],
        }
    )


def step(
    step_id: str,
    query: str,
    *,
    depends_on: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": step_id,
        "title": f"Check {query}",
        "tool_name": "knowledge_search",
        "arguments": {"query": query},
        "success_criteria": "At least one grounded source is available",
        "depends_on": depends_on or [],
    }


class ScriptedTransport(LLMTransport):
    def __init__(
        self,
        *,
        completions: list[LLMResponse] | None = None,
        streams: list[list[TextDelta | TurnDone]] | None = None,
    ) -> None:
        self.completions = completions or []
        self.streams = streams or []
        self.complete_requests: list[list[dict[str, Any]]] = []
        self.stream_requests: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> LLMResponse:
        self.complete_requests.append([dict(message) for message in messages])
        if not self.completions:
            raise AssertionError("unexpected structured model call")
        return self.completions.pop(0)

    async def stream_turn(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[TextDelta | TurnDone]:
        self.stream_requests.append([dict(message) for message in messages])
        if not self.streams:
            raise AssertionError("unexpected stream call")
        for event in self.streams.pop(0):
            yield event


class SearchTool(AgentTool):
    name = "knowledge_search"
    description = "Search permission-filtered enterprise documents."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        empty: set[str] | None = None,
        delay: float = 0,
    ) -> None:
        self.empty = empty or set()
        self.delay = delay
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.cancelled = False

    async def execute(self, arguments: dict[str, Any], _: AgentContext) -> ToolResult:
        query = str(arguments["query"])
        self.calls.append(query)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.active -= 1
        if query in self.empty:
            return ToolResult(
                call_id="",
                content="No matching documents.",
                metadata={"outcome": "empty", "result_count": 0},
            )
        evidence_id = f"ev-{query.replace(' ', '-')}"
        evidence = Evidence(
            id=evidence_id,
            document_id=f"doc-{query}",
            title=f"Source for {query}",
            content=f"Grounded evidence for {query}.",
            source="confluence",
            uri=f"https://knowledge.example/{evidence_id}",
            relevance_score=0.91,
        )
        return ToolResult(
            call_id="",
            content=f"[{evidence_id}] {evidence.content}",
            evidence=[evidence],
            metadata={"outcome": "success", "result_count": 1},
        )


class StrictRunTrace:
    def __init__(self) -> None:
        self.execution_mode: ExecutionMode | None = None

    def complete(
        self,
        *,
        answer: str,
        answer_characters: int,
        turn_count: int,
        tool_call_count: int,
        sources_found: int,
        sources_used: int,
        execution_mode: ExecutionMode,
    ) -> None:
        del (
            answer,
            answer_characters,
            turn_count,
            tool_call_count,
            sources_found,
            sources_used,
        )
        self.execution_mode = execution_mode

    def fail(self, *, stage: str) -> None:
        del stage


class StrictTracing:
    def __init__(self) -> None:
        self.run_trace = StrictRunTrace()

    def agent_run(self, **_: Any) -> Any:
        return nullcontext(self.run_trace)

    def model_turn(self, **_: Any) -> Any:
        return nullcontext(None)

    def capability(self, **_: Any) -> Any:
        return nullcontext(None)


def make_loop(
    transport: LLMTransport,
    tool: SearchTool | None = None,
    *,
    timeout: float = 1,
    max_tool_calls: int = 6,
    tracing: Any | None = None,
) -> tuple[AgentLoop, SearchTool]:
    search = tool or SearchTool()
    registry = ToolRegistry()
    registry.register(search)
    return (
        AgentLoop(
            transport,
            registry,
            enable_interleaved=True,
            tool_timeout_seconds=timeout,
            max_tool_calls=max_tool_calls,
            tracing=tracing,
        ),
        search,
    )


async def collect(loop: AgentLoop, message: str) -> list[Any]:
    return [event async for event in loop.run_stream(message, CONTEXT)]


@pytest.mark.asyncio
async def test_semantic_router_keeps_direct_answer_free_of_activity() -> None:
    transport = ScriptedTransport(
        completions=[direct()],
        streams=[[TextDelta("Hello "), TextDelta("there."), TurnDone("stop")]]
    )
    loop, tool = make_loop(transport)

    events = await collect(loop, "Hello")

    assert len(transport.complete_requests) == 1
    assert tool.calls == []
    assert "".join(event.text for event in events if isinstance(event, FinalAnswerDelta)) == "Hello there."
    assert not any(isinstance(event, CommentaryDelta) for event in events)
    assert not any(isinstance(event, InterleavedToolStarted) for event in events)


@pytest.mark.asyncio
async def test_vietnamese_knowledge_request_uses_retrieval_tool() -> None:
    transport = ScriptedTransport(
        completions=[plan(step("step_1", "thông tin sản phẩm vay"))],
        streams=[[TextDelta("Đã tìm thấy thông tin."), TurnDone("stop")]],
    )
    loop, tool = make_loop(transport)

    events = await collect(loop, "search thông tin sản phẩm vay")

    assert tool.calls == ["thông tin sản phẩm vay"]
    assert any(isinstance(event, InterleavedToolStarted) for event in events)
    assert isinstance(events[-1], RunCompleted)


@pytest.mark.asyncio
async def test_follow_up_context_is_rendered_into_planner_and_final_prompt() -> None:
    transport = ScriptedTransport(
        completions=[plan(step("step_1", "lãi suất sản phẩm vay Easy"))],
        streams=[[TextDelta("Lãi suất được ghi trong tài liệu."), TurnDone("stop")]],
    )
    loop, tool = make_loop(transport)
    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=["employee"],
        history=(
            ConversationMessage(role="user", content="Tra cứu sản phẩm vay Easy"),
            ConversationMessage(
                role="assistant",
                content="Sản phẩm vay Easy có thông tin trong nguồn nội bộ.",
            ),
        ),
    )

    events = [
        event
        async for event in loop.run_stream("Còn lãi suất thì sao?", context)
    ]

    planner_prompt = transport.complete_requests[0][1]["content"]
    assert "sản phẩm vay Easy" in planner_prompt
    assert "Còn lãi suất thì sao?" in planner_prompt
    assert transport.stream_requests[0][1:3] == [
        {"role": "user", "content": "Tra cứu sản phẩm vay Easy"},
        {
            "role": "assistant",
            "content": "Sản phẩm vay Easy có thông tin trong nguồn nội bộ.",
        },
    ]
    assert tool.calls == ["lãi suất sản phẩm vay Easy"]
    assert isinstance(events[-1], RunCompleted)


@pytest.mark.asyncio
async def test_transforming_prior_knowledge_answer_does_not_retrieve_again() -> None:
    transport = ScriptedTransport(
        completions=[direct()],
        streams=[[TextDelta("The fee is one percent."), TurnDone("stop")]],
    )
    loop, tool = make_loop(transport)
    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=["employee"],
        history=(
            ConversationMessage(role="user", content="Phí sản phẩm vay là bao nhiêu?"),
            ConversationMessage(role="assistant", content="Phí là một phần trăm."),
        ),
    )

    events = [
        event
        async for event in loop.run_stream(
            "Dịch câu trả lời về phí sang tiếng Anh",
            context,
        )
    ]

    assert len(transport.complete_requests) == 1
    assert tool.calls == []
    assert isinstance(events[-1], RunCompleted)


@pytest.mark.asyncio
async def test_router_rejects_direct_mode_when_it_declares_retrieval_required() -> None:
    transport = ScriptedTransport(
        completions=[
            response(
                {
                    "mode": "direct",
                    "requires_knowledge_retrieval": True,
                    "commentary": None,
                    "steps": [],
                }
            )
        ],
        streams=[[TextDelta("Should not stream."), TurnDone("stop")]],
    )
    loop, tool = make_loop(transport)

    events = await collect(loop, "search internal loan products")

    assert tool.calls == []
    assert transport.stream_requests == []
    assert events[-1].type == "run_failed"


@pytest.mark.asyncio
async def test_plan_rejects_invalid_tool_arguments_before_execution() -> None:
    invalid_step = step("step_1", "loan products")
    invalid_step["arguments"] = {"unexpected": "value"}
    transport = ScriptedTransport(
        completions=[plan(invalid_step)],
        streams=[[TextDelta("Should not stream."), TurnDone("stop")]],
    )
    loop, tool = make_loop(transport)

    events = await collect(loop, "search internal loan products")

    assert tool.calls == []
    assert transport.stream_requests == []
    assert events[-1].type == "run_failed"


@pytest.mark.asyncio
async def test_interleaved_completion_records_typed_execution_mode() -> None:
    transport = ScriptedTransport(
        completions=[direct()],
        streams=[[TextDelta("Hello."), TurnDone("stop")]]
    )
    tracing = StrictTracing()
    loop, _ = make_loop(transport, tracing=tracing)

    events = await collect(loop, "Hello")

    assert isinstance(events[-1], RunCompleted)
    assert tracing.run_trace.execution_mode is ExecutionMode.DIRECT


@pytest.mark.asyncio
async def test_planned_steps_run_in_parallel_without_unnecessary_critic() -> None:
    transport = ScriptedTransport(
        completions=[
            plan(
                step("step_1", "annual leave eligibility"),
                step("step_2", "annual leave entitlement"),
                step("step_3", "annual leave exceptions"),
            )
        ],
        streams=[[TextDelta("Comparison complete."), TurnDone("stop")]],
    )
    loop, tool = make_loop(transport, SearchTool(delay=0.01))

    events = await collect(loop, "Explain the annual leave policy")

    assert tool.max_active == 3
    assert set(tool.calls) == {
        "annual leave eligibility",
        "annual leave entitlement",
        "annual leave exceptions",
    }
    assert len(transport.complete_requests) == 1
    planner_prompt = transport.complete_requests[0][-1]["content"]
    assert "<retrieval_query_count>3</retrieval_query_count>" in planner_prompt
    assert sum(isinstance(event, InterleavedToolStarted) for event in events) == 3
    assert sum(isinstance(event, IntermediateFindingDelta) for event in events) == 3
    assert isinstance(events[-1], RunCompleted)


@pytest.mark.asyncio
async def test_critic_refines_only_weak_step_once() -> None:
    transport = ScriptedTransport(
        completions=[
            plan(step("step_1", "broad policy")),
            response(
                {
                    "sufficient": False,
                    "action": "refine",
                    "refined_arguments": {"query": "specific policy"},
                    "reason": "The first search was empty.",
                }
            ),
        ],
        streams=[[TextDelta("The specific source is available."), TurnDone("stop")]],
    )
    loop, tool = make_loop(transport, SearchTool(empty={"broad policy"}))

    events = await collect(loop, "Investigate the internal policy")

    assert tool.calls == ["broad policy", "specific policy"]
    assert len(transport.complete_requests) == 2
    assert [event.attempt for event in events if isinstance(event, InterleavedToolStarted)] == [1, 2]
    assert "Trying a more focused approach" not in "".join(
        event.text for event in events if isinstance(event, FinalAnswerDelta)
    )


@pytest.mark.asyncio
async def test_partial_failure_keeps_successful_independent_step() -> None:
    transport = ScriptedTransport(
        completions=[
            plan(step("step_1", "missing"), step("step_2", "available")),
            response(
                {
                    "sufficient": False,
                    "action": "stop",
                    "refined_arguments": None,
                    "reason": "No safe refinement is available.",
                }
            ),
        ],
        streams=[[TextDelta("One source was available."), TurnDone("stop")]],
    )
    loop, tool = make_loop(transport, SearchTool(empty={"missing"}, delay=0.01))

    events = await collect(loop, "Compare internal missing and available records")

    assert set(tool.calls) == {"missing", "available"}
    completed = [event for event in events if isinstance(event, InterleavedToolCompleted)]
    assert {event.status for event in completed} == {"failed", "completed"}
    assert sum(isinstance(event, IntermediateFindingDelta) for event in events) == 1


@pytest.mark.asyncio
async def test_final_answer_is_truly_incremental() -> None:
    release = asyncio.Event()

    class PausingTransport(ScriptedTransport):
        async def stream_turn(self, *args: Any, **kwargs: Any) -> Any:
            yield TextDelta("first ")
            await release.wait()
            yield TextDelta("second")
            yield TurnDone("stop")

    loop, _ = make_loop(PausingTransport(completions=[direct()]))
    stream = loop.run_stream("Hello", CONTEXT).__aiter__()

    assert (await anext(stream)).type == "run_started"
    first = await asyncio.wait_for(anext(stream), timeout=0.1)
    assert first == FinalAnswerDelta("first ")
    release.set()
    remaining = [event async for event in stream]
    assert "".join(
        event.text for event in [first, *remaining] if isinstance(event, FinalAnswerDelta)
    ) == "first second"


@pytest.mark.asyncio
async def test_split_citation_marker_and_event_sequence_are_preserved() -> None:
    evidence_id = "ev-annual-leave"
    transport = ScriptedTransport(
        completions=[plan(step("step_1", "annual leave"))],
        streams=[[
            TextDelta(f"Policy [[cite:{evidence_id[:7]}"),
            TextDelta(f"{evidence_id[7:]}]] applies."),
            TurnDone("stop"),
        ]],
    )
    loop, _ = make_loop(transport)

    events = await collect(loop, "Summarize the internal annual leave policy")

    assert any(isinstance(event, CitationEvent) for event in events)
    assert "".join(event.text for event in events if isinstance(event, FinalAnswerDelta)) == "Policy  applies."
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert len({event.event_id for event in events}) == len(events)
    assert events.index(next(event for event in events if isinstance(event, CommentaryDelta))) < events.index(
        next(event for event in events if isinstance(event, InterleavedToolStarted))
    )


@pytest.mark.asyncio
async def test_tool_timeout_cancels_work_and_completes_partial_run() -> None:
    transport = ScriptedTransport(
        completions=[
            plan(step("step_1", "slow")),
            response(
                {
                    "sufficient": False,
                    "action": "stop",
                    "refined_arguments": None,
                    "reason": "The timed-out step cannot be safely retried.",
                }
            ),
        ],
        streams=[[TextDelta("The source could not be checked."), TurnDone("stop")]],
    )
    tool = SearchTool(delay=1)
    loop, _ = make_loop(transport, tool, timeout=0.01)

    events = await collect(loop, "Investigate the internal slow source")

    assert tool.cancelled is True
    completed = next(event for event in events if isinstance(event, InterleavedToolCompleted))
    assert completed.status == "timeout"
    assert isinstance(events[-1], RunCompleted)


@pytest.mark.asyncio
async def test_cancelling_stream_propagates_to_active_tool() -> None:
    transport = ScriptedTransport(
        completions=[plan(step("step_1", "slow"))],
        streams=[[TextDelta("unused"), TurnDone("stop")]],
    )
    tool = SearchTool(delay=10)
    loop, _ = make_loop(transport, tool, timeout=20)
    stream = loop.run_stream("Investigate the internal slow source", CONTEXT).__aiter__()

    while True:
        event = await anext(stream)
        if isinstance(event, InterleavedToolStarted):
            break
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert tool.cancelled is True
