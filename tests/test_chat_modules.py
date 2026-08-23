from __future__ import annotations

import json
import sys
import asyncio
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent import AgentConfig, ConversationMemory
from bothesis.agent.citation import CitationRenderer
from bothesis.agent.models import (
    AgentContext,
    ConversationDocument,
    ConversationMessage,
    Evidence,
    ToolContext,
    ToolOutput,
)
from bothesis.agent.protocol import FunctionCallItem, InputText
from bothesis.agent.tools import Tool, ToolDefinition, ToolExecutor, ToolRegistry


def test_conversation_policy_keeps_newest_content_within_budget() -> None:
    policy = ConversationMemory(
        config=AgentConfig(
            max_history_messages=2,
            max_history_characters=9,
            recent_history_messages=2,
        ),
    )
    history = (
        ConversationMessage(role="user", content="abcdef"),
        ConversationMessage(role="assistant", content="xyz"),
    )

    bounded = policy.bounded(history)

    assert json.loads(bounded) == [
        {"role": "user", "content": "abcdef"},
        {"role": "assistant", "content": "xyz"},
    ]


def test_conversation_policy_preserves_recent_turn_and_summarizes_only_older() -> None:
    policy = ConversationMemory(
        config=AgentConfig(
            max_history_messages=6,
            max_history_characters=200,
            recent_history_messages=2,
        ),
    )
    history = (
        ConversationMessage(role="user", content="Earlier product question"),
        ConversationMessage(role="assistant", content="Earlier product answer"),
        ConversationMessage(role="user", content="What are its fees?"),
        ConversationMessage(role="assistant", content="The fee is documented."),
    )

    window = policy.window(history)

    assert [message.content for message in window.recent_messages] == [
        "What are its fees?",
        "The fee is documented.",
    ]
    assert [message.content for message in window.older_messages] == [
        "Earlier product question",
        "Earlier product answer",
    ]


@pytest.mark.asyncio
async def test_conversation_context_uses_distinct_xml_sections() -> None:
    evidence = Evidence(
        id="ev-1",
        item_id="doc-1",
        chunk_id="chunk-1",
        title="Leave policy",
        content="Employees receive 20 days of annual leave.",
    )
    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=[],
        documents=(
            ConversationDocument(
                id="doc-1",
                title="Leave policy <draft>",
                content_type="text/plain",
                mode="indexed",
                citation_id="ev-1",
                extracted_text="Annual leave <must be cited>.",
                evidence=(evidence,),
            ),
        ),
    )

    turn_input = await ConversationMemory(config=AgentConfig()).prepare(
        "What is the leave policy?",
        context,
    )

    assert turn_input.instructions is not None
    assert "<agent_instructions>" in turn_input.instructions
    assert "<conversation_document_policy>" in turn_input.instructions
    assert "<documents>" in turn_input.instructions
    assert "Leave policy &lt;draft&gt;" in turn_input.instructions
    texts = [
        part.text
        for item in turn_input.items
        for part in item.content
        if isinstance(part, InputText)
    ]
    assert texts[0] == "<user_message>What is the leave policy?</user_message>"
    assert "<attached_document>" in texts[1]
    assert "Annual leave &lt;must be cited&gt;." in texts[1]
    assert "<retrieved_document_evidence>" in texts[2]
    assert "<evidence_id>ev-1</evidence_id>" in texts[2]


@pytest.mark.asyncio
async def test_citation_renderer_carries_split_markers_between_deltas() -> None:
    evidence = {
        "ev-1": Evidence(
            id="ev-1",
            item_id="doc-1",
            chunk_id="chunk-1",
            title="Leave policy",
            content="Grounded content",
        )
    }
    used_evidence_ids: set[str] = set()

    events = [
        event
        async for event in CitationRenderer().render(
            ("Policy [[cite:ev", "-1]] applies"),
            evidence,
            used_evidence_ids,
        )
    ]

    assert events == [("Policy ", None), ("", "ev-1"), (" applies", None)]
    assert used_evidence_ids == {"ev-1"}


# Native OpenRouter tool-call normalization is covered by
# tests/bothesis/agent/test_openrouter_adapter.py, which drives the adapter
# through its public streaming contract instead of a private helper.


@pytest.mark.asyncio
async def test_tool_executor_runs_independent_calls_concurrently_and_matches_call_ids() -> None:
    class ParallelEchoTool(Tool):
        def __init__(self) -> None:
            self.active = 0
            self.overlapped = False

        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="echo",
                description="Echo a value.",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            )

        async def execute(self, arguments: dict[str, object], context: ToolContext) -> ToolOutput:
            self.active += 1
            self.overlapped = self.overlapped or self.active > 1
            await asyncio.sleep(0.01)
            self.active -= 1
            return ToolOutput(content=str(arguments["value"]))

    registry = ToolRegistry()
    tool = ParallelEchoTool()
    registry.register(tool)
    batch = await ToolExecutor(
        registry, timeout_seconds=1, max_output_characters=100
    ).execute(
        (
            FunctionCallItem(call_id="first", name="echo", arguments='{"value":"one"}'),
            FunctionCallItem(call_id="second", name="echo", arguments='{"value":"two"}'),
        ),
        context=ToolContext(agent_context=AgentContext(user_id="u", tenant_id="t", roles=[])),
        remaining_calls=2,
        previous_signatures=set(),
        evidence={},
    )

    assert tool.overlapped is True
    assert [(item.call_id, item.output) for item in batch.output_items] == [
        ("first", "one"),
        ("second", "two"),
    ]

    blocked = await ToolExecutor(
        registry, timeout_seconds=1, max_output_characters=100
    ).execute(
        (FunctionCallItem(call_id="blocked", name="echo", arguments='{"value":"no"}'),),
        context=ToolContext(agent_context=AgentContext(user_id="u", tenant_id="t", roles=[])),
        remaining_calls=1,
        previous_signatures=set(),
        evidence={},
        allowed_tool_names=(),
    )

    assert blocked.executed_call_count == 0
    assert blocked.output_items[0].output == (
        "Tool error: Tool is not available for this request."
    )
