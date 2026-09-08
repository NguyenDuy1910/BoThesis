"""Focused contracts for the session / turn / step runtime."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TESTS_ROOT))
sys.path.insert(0, str(_TESTS_ROOT.parent / "backend"))

from native_responses import ScriptedResponsesTransport, completed, created, function_call, message

from bothesis.agent import (
    ContextManager,
    ResolvedStepSettings,
    Session,
    SessionConfiguration,
    SessionServices,
    TurnContext,
    TurnEnvironmentSnapshot,
)
from bothesis.agent.models import AgentContext, ToolOutput
from bothesis.agent.protocol import FunctionCallItem
from bothesis.agent.tools import (
    ToolExecutor,
    ToolInvocation,
    ToolOrchestrator,
    ToolRegistry,
    ToolSpec,
)
from bothesis.agent.turn import run_turn


class Lookup(ToolExecutor):
    def __init__(self) -> None:
        self.invocations: list[ToolInvocation] = []

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_search",
            description="Search knowledge.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        self.invocations.append(invocation)
        return ToolOutput(content=f"found {invocation.payload.arguments['query']}")


class RecordingSession(Session):
    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self.steps = []

    async def capture_step_context(self, turn: TurnContext):
        step = await super().capture_step_context(turn)
        self.steps.append(step)
        return step


def _context(*, allowed: tuple[str, ...] | None = ("knowledge_search",)) -> AgentContext:
    return AgentContext(user_id="user", tenant_id="tenant", roles=[], allowed_tool_names=allowed)


def _turn(context: AgentContext) -> TurnContext:
    settings = ResolvedStepSettings(
        model=None,
        temperature=None,
        max_output_tokens=None,
        parallel_tool_calls=True,
    )
    return TurnContext(
        user_input="What is the leave policy?",
        environment=TurnEnvironmentSnapshot(agent_context=context),
        initial_settings=settings,
        current_settings=settings,
    )


def _session(transport: ScriptedResponsesTransport, registry: ToolRegistry) -> RecordingSession:
    configuration = SessionConfiguration(max_model_turns=3, max_tool_rounds=2)
    return RecordingSession(
        configuration,
        SessionServices(model=transport, tool_registry=registry),
        ContextManager(configuration=configuration),
    )


@pytest.mark.asyncio
async def test_turn_recaptures_step_and_returns_to_model_after_a_tool() -> None:
    transport = ScriptedResponsesTransport(
        [
            [
                *created("resp_a"),
                *function_call(
                    item_id="fc_1",
                    output_index=0,
                    call_id="call_1",
                    name="knowledge_search",
                    argument_deltas=['{"query":"leave"}'],
                ),
                *completed("resp_a"),
            ],
            [
                *created("resp_b"),
                *message(item_id="msg_1", output_index=0, deltas=["Leave is 20 days."], phase="final_answer"),
                *completed("resp_b"),
            ],
        ]
    )
    lookup = Lookup()
    registry = ToolRegistry()
    registry.register(lookup)
    session = _session(transport, registry)

    events = [event async for event in run_turn(session, _turn(_context()))]

    assert len(session.steps) == 2
    assert session.steps[0] is not session.steps[1]
    assert lookup.invocations[0].step_context is session.steps[0]
    assert transport.requests[1]["input"][-1]["type"] == "function_call_output"
    assert events[-1].type == "response.completed"


@pytest.mark.asyncio
async def test_step_router_is_captured_from_current_turn_visibility() -> None:
    transport = ScriptedResponsesTransport([])
    registry = ToolRegistry()
    registry.register(Lookup())
    session = _session(transport, registry)
    turn = _turn(_context())

    first = await session.capture_step_context(turn)
    turn.environment = TurnEnvironmentSnapshot(agent_context=_context(allowed=()))
    second = await session.capture_step_context(turn)

    assert [spec.name for spec in first.tool_router.model_visible_specs] == ["knowledge_search"]
    assert second.tool_router.model_visible_specs == ()


@pytest.mark.asyncio
async def test_hidden_tool_call_is_rejected_by_the_originating_step_router() -> None:
    transport = ScriptedResponsesTransport([])
    lookup = Lookup()
    registry = ToolRegistry()
    registry.register(lookup)
    session = _session(transport, registry)
    turn = _turn(_context(allowed=()))
    step = await session.capture_step_context(turn)

    batch = await ToolOrchestrator(
        timeout_seconds=1,
        max_output_characters=1_000,
    ).execute(
        (FunctionCallItem(call_id="call_1", name="knowledge_search", arguments='{"query":"leave"}'),),
        session=session,
        step_context=step,
        remaining_calls=1,
    )

    assert lookup.invocations == []
    assert batch.executed_call_count == 0
    assert batch.output_items[0].output == "Tool error: Tool is not exposed for this sampling step."
