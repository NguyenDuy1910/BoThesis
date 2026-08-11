from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import (
    CitationEvent,
    ConversationMessage,
    Evidence,
    MessageDelta,
    ToolCallDelta,
    TurnDone,
)
from bothesis.chat.citation_processor import process_citation_buffer
from bothesis.chat.compression import ConversationContextPolicy
from bothesis.chat.event_emitter import ModelTurnAccumulator


def test_conversation_policy_keeps_newest_content_within_budget() -> None:
    policy = ConversationContextPolicy(
        max_messages=2,
        max_characters=9,
        compression_threshold=10,
        max_compressed_characters=4,
        recent_messages=2,
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
    assert not policy.needs_compression(policy.window(history))


def test_conversation_policy_preserves_recent_turn_and_summarizes_only_older() -> None:
    policy = ConversationContextPolicy(
        max_messages=6,
        max_characters=200,
        compression_threshold=10,
        max_compressed_characters=50,
        recent_messages=2,
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
    assert policy.needs_compression(window)


def test_citation_processor_carries_split_markers_between_deltas() -> None:
    evidence = {
        "ev-1": Evidence(
            id="ev-1",
            document_id="doc-1",
            title="Leave policy",
            content="Grounded content",
        )
    }

    first_events, carry = process_citation_buffer("Policy [[cite:ev", evidence)
    second_events, carry = process_citation_buffer(f"{carry}-1]] applies", evidence)

    assert first_events == [MessageDelta("Policy ")]
    assert second_events == [
        CitationEvent(evidence_id="ev-1", title="Leave policy"),
        MessageDelta(" applies"),
    ]
    assert carry == ""


def test_model_turn_accumulator_normalizes_native_tool_calls() -> None:
    accumulator = ModelTurnAccumulator()
    accumulator.feed(
        ToolCallDelta(
            call_id="tool-1",
            name="knowledge_search",
            arguments='{"query":"leave',
        )
    )
    accumulator.feed(
        ToolCallDelta(
            call_id="tool-1",
            name="",
            arguments=' policy"}',
        )
    )
    accumulator.feed(TurnDone("tool_calls", model="openai/gpt-5.4-mini"))

    turn = accumulator.result()
    assert turn.text == ""
    assert turn.tool_calls[0].name == "knowledge_search"
    assert turn.tool_calls[0].arguments == {"query": "leave policy"}
