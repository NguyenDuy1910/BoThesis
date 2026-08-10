from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.capabilities import (
    CapabilityExecutionError,
    KnowledgeCapabilityExecutor,
    QueryRewrite,
)
from bothesis.agent.models import AgentContext, TextDelta, ToolCallDelta, TurnDone
from bothesis.agent.prompts.template_render import (
    PromptRenderError,
    load_prompt,
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
}
CONTEXT = AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[])


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


@pytest.mark.asyncio
async def test_capability_executor_returns_typed_output() -> None:
    transport = CompletionTransport('{"query":"standalone leave policy"}')
    executor = KnowledgeCapabilityExecutor(transport)

    result = await executor.structured(
        "query_rewrite",
        QueryRewrite,
        values={"conversation": "[]", "query": "What about leave?"},
        ctx=CONTEXT,
        step=1,
    )

    assert result.value == QueryRewrite(query="standalone leave policy")
    request = transport.requests[0][0]
    assert request["role"] == "user"
    assert request["content"].index("<instructions>") < request["content"].index(
        "<input>"
    )


@pytest.mark.asyncio
async def test_capability_executor_rejects_malformed_structured_output() -> None:
    executor = KnowledgeCapabilityExecutor(CompletionTransport("not json"))

    with pytest.raises(CapabilityExecutionError, match="invalid response"):
        await executor.structured(
            "query_rewrite",
            QueryRewrite,
            values={"conversation": "[]", "query": "leave"},
            ctx=CONTEXT,
            step=1,
        )
