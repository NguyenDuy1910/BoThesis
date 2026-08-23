"""Orchestration tests for one user turn.

A turn is a chain of OpenResponses responses: the loop samples, executes any
function calls the response requested, appends the resulting
``function_call_output`` items, and samples again. These tests drive the public
:class:`Agent` so the whole path — transport, adapter, citation projection,
reducer, loop — is exercised as it runs in production, and the turn-level
behaviour is asserted for every supported provider.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TESTS_ROOT))
sys.path.insert(0, str(_TESTS_ROOT.parent / "backend"))

from native_responses import (
    ScriptedResponsesTransport,
    completed,
    created,
    function_call,
    incomplete,
    message,
)

from bothesis.agent import Agent, AgentConfig
from bothesis.agent.models import (
    AgentContext,
    ConversationDocument,
    Evidence,
    ToolContext,
    ToolOutput,
)
from bothesis.agent.tools import Tool, ToolDefinition, ToolRegistry
from bothesis.agent.transports import RESPONSES_PROVIDERS
from bothesis.connector.protocol import CitationInfo
from bothesis.connector.protocol import CitationSpan

PROVIDERS = sorted(RESPONSES_PROVIDERS)


class EchoTool(Tool):
    """A minimal tool whose output is deterministic."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="lookup",
            description="Look a term up.",
            input_schema={
                "type": "object",
                "properties": {"term": {"type": "string"}},
                "required": ["term"],
                "additionalProperties": False,
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolOutput:
        return ToolOutput(content=f"definition of {arguments['term']}")


def registry_with_lookup() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(EchoTool())
    return registry


def context(**overrides: Any) -> AgentContext:
    payload: dict[str, Any] = {
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "roles": [],
    }
    payload.update(overrides)
    return AgentContext(**payload)


async def run(agent: Agent, user_message: str = "hello", **overrides: Any) -> list[Any]:
    return [event async for event in agent.run(user_message, context(**overrides))]


def commentary_then_tool_call(term: str = "leave") -> list[Any]:
    return [
        *created("resp_a"),
        *message(
            item_id="msg_1", output_index=0, deltas=["Let me look that up. "], phase="commentary"
        ),
        *function_call(
            item_id="fc_1",
            output_index=1,
            call_id="call-1",
            name="lookup",
            argument_deltas=['{"term":"', f'{term}"}}'],
        ),
        *completed("resp_a"),
    ]


def final_answer(text: str = "Leave is 20 days.") -> list[Any]:
    return [
        *created("resp_b"),
        *message(item_id="msg_2", output_index=0, deltas=[text], phase="final_answer"),
        *completed("resp_b"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_a_turn_chains_two_sampling_requests_around_one_tool_call(
    provider: str,
) -> None:
    transport = ScriptedResponsesTransport(
        [commentary_then_tool_call(), final_answer()], provider=provider
    )

    events = await run(Agent(transport, registry_with_lookup()))
    created_events = [event for event in events if event.type == "response.created"]
    completed_events = [event for event in events if event.type == "response.completed"]

    assert len(created_events) == 2
    assert len(completed_events) == 2
    # The second response records the first, so a client can chain the turn.
    assert created_events[0].response.previous_response_id is None
    assert created_events[1].response.previous_response_id == "resp_a"
    # Commentary and the final answer are distinguished by phase, not by event.
    assert completed_events[0].response.commentary_text == "Let me look that up. "
    assert completed_events[0].response.final_answer_text == ""
    assert completed_events[1].response.final_answer_text == "Leave is 20 days."
    # The tool observation is replayed as a canonical ``function_call_output``.
    replayed = transport.requests[1]["input"]
    assert replayed[-1] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "definition of leave",
    }
    assert replayed[-2] == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "lookup",
        "arguments": '{"term":"leave"}',
        "id": "fc_1",
    }
    # ``phase`` is resent on the follow-up, which the specification requires.
    assert replayed[-3]["phase"] == "commentary"


@pytest.mark.asyncio
async def test_sequence_numbers_increase_monotonically_across_the_whole_turn() -> None:
    transport = ScriptedResponsesTransport(
        [commentary_then_tool_call(), final_answer()]
    )

    events = await run(Agent(transport, registry_with_lookup()))

    assert [event.sequence_number for event in events] == list(
        range(1, len(events) + 1)
    )


@pytest.mark.asyncio
async def test_a_provider_that_omits_phase_still_yields_a_final_answer() -> None:
    """``phase`` is optional; the reducer resolves it when the response settles."""

    transport = ScriptedResponsesTransport(
        [
            [
                *created("resp_a"),
                *message(item_id="msg_1", output_index=0, deltas=["Checking."]),
                *function_call(
                    item_id="fc_1",
                    output_index=1,
                    call_id="call-1",
                    name="lookup",
                    argument_deltas=['{"term":"x"}'],
                ),
                *completed("resp_a"),
            ],
            [
                *created("resp_b"),
                *message(item_id="msg_2", output_index=0, deltas=["Answer."]),
                *completed("resp_b"),
            ],
        ]
    )

    events = await run(Agent(transport, registry_with_lookup()))
    settled = [event.response for event in events if event.type == "response.completed"]

    assert settled[0].messages[0].phase == "commentary"
    assert settled[1].messages[0].phase == "final_answer"
    assert settled[1].final_answer_text == "Answer."


@pytest.mark.asyncio
async def test_text_reaches_the_client_before_the_response_settles() -> None:
    release = asyncio.Event()

    class PausingTransport(ScriptedResponsesTransport):
        async def stream_response(self, *, input: Any, model: Any = None, **params: Any):
            self.requests.append({"input": list(input), "model": model, **params})
            script = message(item_id="msg_1", output_index=0, deltas=["first "])

            async def iterator():
                for event in created("resp_a"):
                    yield event
                # item.added, part.added, the first delta
                for event in script[:3]:
                    yield event
                await release.wait()
                for event in script[3:]:
                    yield event
                for event in completed("resp_a"):
                    yield event

            return iterator()

    stream = Agent(PausingTransport([]), ToolRegistry()).run("hello", context())
    seen = [await asyncio.wait_for(anext(stream), timeout=0.2) for _ in range(5)]

    assert [event.type for event in seen] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
    ]
    assert seen[-1].delta == "first "

    release.set()
    remaining = [event async for event in stream]
    assert remaining[-1].type == "response.completed"
    assert remaining[-1].response.final_answer_text == "first "


@pytest.mark.asyncio
async def test_citation_markers_become_annotations_and_leave_the_text_clean() -> None:
    evidence = Evidence(
        id="ev-1",
        item_id="doc-1",
        chunk_id="chunk-1",
        title="Policy",
        content="Grounded policy",
        citation=CitationInfo(spans=(CitationSpan(page=3),)),
    )
    document = ConversationDocument(
        id="doc-1",
        title="Policy",
        content_type="text/plain",
        mode="indexed",
        citation_id="ev-1",
        evidence=(evidence,),
    )
    transport = ScriptedResponsesTransport(
        [
            [
                *created("resp_a"),
                *message(
                    item_id="msg_1",
                    output_index=0,
                    deltas=["Leave is 20 days [[cite:", "ev-1]] per year."],
                    phase="final_answer",
                ),
                *completed("resp_a"),
            ]
        ]
    )

    events = await run(Agent(transport, ToolRegistry()), documents=(document,))
    deltas = [
        event.delta for event in events if event.type == "response.output_text.delta"
    ]
    annotations = [
        event
        for event in events
        if event.type == "response.output_text.annotation.added"
    ]
    response = events[-1].response

    assert "".join(deltas) == "Leave is 20 days  per year."
    assert "[[cite:" not in "".join(deltas)
    assert len(annotations) == 1
    assert annotations[0].annotation["type"] == "bothesis:document_citation"
    assert annotations[0].annotation["citation"]["spans"][0]["page"] == 3
    assert annotations[0].annotation_index == 0
    assert response.final_answer_text == "Leave is 20 days  per year."
    assert response.output_annotations[0]["citation"]["id"] == "ev-1"


@pytest.mark.asyncio
async def test_a_partial_citation_marker_is_the_only_text_held_back() -> None:
    """Streaming stays incremental: text before a marker is not buffered."""

    release = asyncio.Event()
    evidence = Evidence(
        id="ev-1", item_id="doc-1", chunk_id="chunk-1", title="Policy", content="Grounded"
    )
    document = ConversationDocument(
        id="doc-1",
        title="Policy",
        content_type="text/plain",
        mode="indexed",
        citation_id="ev-1",
        evidence=(evidence,),
    )

    class SplitTransport(ScriptedResponsesTransport):
        async def stream_response(self, *, input: Any, model: Any = None, **params: Any):
            self.requests.append({"input": list(input), "model": model, **params})
            script = message(
                item_id="msg_1",
                output_index=0,
                deltas=["Policy [[cite:", "ev-1]] applies"],
            )

            async def iterator():
                for event in created("resp_a"):
                    yield event
                # item.added, part.added, first delta
                for event in script[:3]:
                    yield event
                await release.wait()
                for event in script[3:]:
                    yield event
                for event in completed("resp_a"):
                    yield event

            return iterator()

    stream = Agent(SplitTransport([]), ToolRegistry()).run(
        "hello", context(documents=(document,))
    )
    seen = [await asyncio.wait_for(anext(stream), timeout=0.2) for _ in range(5)]

    assert seen[-1].type == "response.output_text.delta"
    assert seen[-1].delta == "Policy "

    release.set()
    remaining = [event async for event in stream]
    assert [
        event.delta
        for event in remaining
        if event.type == "response.output_text.delta"
    ] == [" applies"]


@pytest.mark.asyncio
async def test_a_literal_bracket_is_not_delayed_when_there_is_no_evidence() -> None:
    transport = ScriptedResponsesTransport(
        [
            [
                *created("resp_a"),
                *message(
                    item_id="msg_1", output_index=0, deltas=["Array[", "0] is first"]
                ),
                *completed("resp_a"),
            ]
        ]
    )

    events = await run(Agent(transport, ToolRegistry()))

    assert [
        event.delta for event in events if event.type == "response.output_text.delta"
    ] == ["Array[", "0] is first"]


@pytest.mark.asyncio
async def test_an_incomplete_response_ends_the_turn_without_a_further_sampling() -> None:
    transport = ScriptedResponsesTransport(
        [
            [
                *created("resp_a"),
                *message(item_id="msg_1", output_index=0, deltas=["truncated"]),
                *incomplete("max_output_tokens", "resp_a"),
            ]
        ]
    )

    events = await run(Agent(transport, ToolRegistry()))

    assert events[-1].type == "response.incomplete"
    assert events[-1].response.incomplete_details.reason == "max_output_tokens"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_a_response_without_an_answer_fails_the_turn() -> None:
    transport = ScriptedResponsesTransport([[*created("resp_a"), *completed("resp_a")]])

    events = await run(Agent(transport, ToolRegistry()))

    assert events[-1].type == "response.failed"
    assert events[-1].response.error.code == "agent_execution_failed"


@pytest.mark.asyncio
async def test_tools_are_withheld_once_the_tool_round_limit_is_reached() -> None:
    transport = ScriptedResponsesTransport(
        [commentary_then_tool_call(), final_answer()]
    )
    config = AgentConfig(max_tool_rounds=1, max_model_turns=3)

    events = await run(Agent(transport, registry_with_lookup(), config=config))

    assert events[-1].type == "response.completed"
    assert len(transport.requests) == 2
    # The follow-up sampling declares no tools once the round budget is spent.
    assert "tools" in transport.requests[0]
    assert "tools" not in transport.requests[1]


@pytest.mark.asyncio
async def test_request_tool_allowlist_can_disable_plugins_for_one_turn() -> None:
    transport = ScriptedResponsesTransport([final_answer("Answered without tools.")])

    events = await run(
        Agent(transport, registry_with_lookup()),
        allowed_tool_names=(),
    )

    assert events[-1].type == "response.completed"
    assert "tools" not in transport.requests[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_message", "overrides", "expected"),
    [
        ("   ", {}, "message must not be empty"),
        ("x" * 5000, {}, "message exceeds the allowed length"),
        ("hello", {"tenant_id": ""}, "tenant and user context are required"),
    ],
)
async def test_invalid_requests_fail_before_any_provider_call(
    user_message: str, overrides: dict[str, Any], expected: str
) -> None:
    transport = ScriptedResponsesTransport([])

    events = await run(Agent(transport, ToolRegistry()), user_message, **overrides)

    assert [event.type for event in events] == ["response.failed"]
    assert events[0].response.error.message == expected
    assert events[0].sequence_number == 1
    assert transport.requests == []


def test_the_shared_script_builders_describe_one_provider_stream() -> None:
    """Both providers are driven by the same script, which is the point."""

    assert isinstance(commentary_then_tool_call(), list)
    assert isinstance(final_answer(), Sequence)
