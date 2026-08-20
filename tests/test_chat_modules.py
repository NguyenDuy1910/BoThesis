from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent import AgentConfig, ConversationMemory, ConversationSession
from bothesis.agent.citation import CitationRenderer
from bothesis.agent.models import (
    AgentContext,
    ConversationDocument,
    ConversationMessage,
    Evidence,
)
from bothesis.agent.protocol import InputText


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
        document_id="doc-1",
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
            document_id="doc-1",
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


def test_openrouter_function_calls_parses_native_tool_call_shape() -> None:
    calls = ConversationSession._openrouter_function_calls(
        [
            {
                "id": "tool-1",
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "arguments": '{"query":"leave policy"}',
                },
            }
        ]
    )

    assert calls[0].name == "knowledge_search"
    assert calls[0].parsed_arguments() == {"query": "leave policy"}
