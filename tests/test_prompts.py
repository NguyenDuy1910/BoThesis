from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.capabilities import (
    CapabilityExecutionError,
    ConversationCompression,
    StructuredCapabilityExecutor,
)
from bothesis.agent.models import AgentContext, TextDelta, ToolCallDelta, TurnDone
from bothesis.agent.prompts.template_render import (
    PromptRenderError,
    load_prompt,
    render_chat_base,
    render_prompt,
)
from bothesis.agent.transports.base import ChatMessage, LLMResponse, LLMTransport

PROMPT_NAMES = {
    "query_rewrite",
    "query_decomposition",
    "retrieval_plan",
    "retrieval_evaluate",
    "retrieval_refine",
    "evidence_synthesis",
    "answer_grounded",
    "clarification",
    "chat_base",
    "conversation_compression",
}
CONTEXT = AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[])
PROMPT_VALUES: dict[str, dict[str, object]] = {
    "answer_grounded": {
        "question": "question",
        "evidence": "[]",
        "synthesis": "{}",
        "missing_information": "[]",
        "source_conflicts": "[]",
    },
    "chat_base": {"current_datetime": "2026-08-10T20:30+07:00"},
    "clarification": {"conversation": "[]", "query": "query"},
    "conversation_compression": {
        "conversation": "[]",
        "current_query": "query",
        "maximum_characters": 2_000,
    },
    "evidence_synthesis": {"question": "question", "evidence": "[]"},
    "query_decomposition": {"query": "query", "maximum_queries": 3},
    "query_rewrite": {"conversation": "[]", "query": "query"},
    "retrieval_evaluate": {
        "question": "question",
        "searched_queries": "[]",
        "evidence": "[]",
        "retrieval_round": 1,
    },
    "retrieval_plan": {
        "question": "question",
        "candidate_queries": "[]",
        "maximum_queries": 3,
    },
    "retrieval_refine": {
        "question": "question",
        "missing_evidence": "[]",
        "previous_queries": "[]",
        "maximum_queries": 3,
    },
}


class CompletionTransport(LLMTransport):
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.requests: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> LLMResponse:
        self.requests.append([dict(message) for message in messages])
        return LLMResponse(
            id="response-1",
            model="openai/gpt-5.4-mini",
            content=self.content,
            finish_reason="stop",
        )

    async def stream_turn(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[TextDelta | ToolCallDelta | TurnDone]:
        raise AssertionError("structured capability must not stream")
        yield  # pragma: no cover


def test_capability_prompt_set_has_stable_xml_prefix_and_runtime_input_last() -> None:
    prompt_directory = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "bothesis"
        / "agent"
        / "prompts"
    )
    prompt_names = {path.stem for path in prompt_directory.glob("*.md")}

    assert prompt_names == PROMPT_NAMES
    for prompt_name in PROMPT_NAMES:
        prompt = load_prompt(prompt_name)
        assert prompt.startswith("<task>")
        assert "<instructions>" in prompt
        assert prompt.rstrip().endswith("</input>")
        assert prompt.index("<instructions>") < prompt.index("<input>")
        if prompt_name != "chat_base":
            assert "<output_contract>" in prompt


def test_every_prompt_renders_all_runtime_values_without_placeholders() -> None:
    assert set(PROMPT_VALUES) == PROMPT_NAMES

    for prompt_name, values in PROMPT_VALUES.items():
        rendered = render_prompt(prompt_name, **values)
        assert "{{" not in rendered
        assert rendered.rstrip().endswith("</input>")


def test_renderer_escapes_runtime_xml_and_rejects_invalid_values() -> None:
    rendered = render_prompt(
        "query_rewrite",
        conversation='[{"content":"A < B"}]',
        query='What about "A&B"?',
    )

    assert "A &lt; B" in rendered
    assert "A&amp;B" in rendered
    assert "&quot;" in rendered
    with pytest.raises(PromptRenderError, match="missing prompt values"):
        render_prompt("query_rewrite", query="missing conversation")
    with pytest.raises(PromptRenderError, match="invalid prompt name"):
        load_prompt("../system")


def test_chat_base_keeps_stable_guidance_before_runtime_context() -> None:
    prompt = render_chat_base(current_datetime="2026-08-10T20:30+07:00")

    assert prompt.startswith("<task>\nYou are BoThesis")
    assert "precise enterprise knowledge and governed business intelligence" in prompt
    assert "2026-08-10T20:30+07:00" in prompt
    assert prompt.index("<instructions>") < prompt.index("<input>")
    assert prompt.rstrip().endswith("</input>")


def test_chat_base_defines_optional_retrieval_grounding_and_concise_answers() -> None:
    prompt = render_chat_base(current_datetime="2026-08-10T20:30+07:00")

    assert "Do not use it for public/general knowledge" in prompt
    assert "A request to shorten, reformat, translate" in prompt
    assert "Do not generate paraphrases seeking the same evidence" in prompt
    assert "[[cite:EVIDENCE_ID]]" in prompt
    assert "add an unsolicited next-step offer" in prompt
    assert "Prior assistant messages provide conversational context" in prompt
    assert "When a capability requires structured output" not in prompt


@pytest.mark.asyncio
async def test_capability_executor_returns_typed_output() -> None:
    transport = CompletionTransport('{"summary":"Policy LP-42 context"}')
    executor = StructuredCapabilityExecutor(transport)

    result = await executor.structured(
        "conversation_compression",
        ConversationCompression,
        values={
            "conversation": "[]",
            "current_query": "What about leave?",
            "maximum_characters": 2_000,
        },
        ctx=CONTEXT,
        step=1,
    )

    assert result.value == ConversationCompression(summary="Policy LP-42 context")
    system_request, capability_request = transport.requests[0]
    assert system_request["role"] == "system"
    assert "You are BoThesis" in system_request["content"]
    assert capability_request["role"] == "user"
    assert capability_request["content"].index("<instructions>") < capability_request[
        "content"
    ].index("<input>")


@pytest.mark.asyncio
async def test_capability_executor_rejects_malformed_structured_output() -> None:
    executor = StructuredCapabilityExecutor(CompletionTransport("not json"))

    with pytest.raises(CapabilityExecutionError, match="invalid response"):
        await executor.structured(
            "conversation_compression",
            ConversationCompression,
            values={
                "conversation": "[]",
                "current_query": "leave",
                "maximum_characters": 2_000,
            },
            ctx=CONTEXT,
            step=1,
        )
