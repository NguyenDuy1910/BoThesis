from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent import AgentConfig, ConversationLoop, ConversationMemory
from bothesis.agent.citation import CitationRenderer
from bothesis.agent.models import CitationEvent, ConversationMessage, Evidence, FinalAnswerDelta


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

    assert events == [
        FinalAnswerDelta(text="Policy "),
        CitationEvent(evidence_id="ev-1", title="Leave policy"),
        FinalAnswerDelta(text=" applies"),
    ]
    assert used_evidence_ids == {"ev-1"}


def test_openrouter_function_calls_parses_native_tool_call_shape() -> None:
    calls = ConversationLoop._openrouter_function_calls(
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
