from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.prompts.template_render import (
    PromptRenderError,
    load_prompt,
    render_agent_base,
    render_prompt,
)


def test_prompt_set_contains_only_the_three_runtime_roles() -> None:
    prompt_directory = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "bothesis"
        / "agent"
        / "prompts"
    )
    prompt_names = {path.stem for path in prompt_directory.glob("*.md")}

    assert prompt_names == {
        "agent_base",
        "capability_base",
        "conversation_compression",
    }
    assert "relevant conversation" in load_prompt("agent_base")


def test_renderer_rejects_invalid_prompt_names() -> None:
    with pytest.raises(PromptRenderError, match="invalid prompt name"):
        load_prompt("../system")


def test_agent_base_defines_lightweight_retrieval_and_grounding_guidance() -> None:
    prompt = render_agent_base()

    assert prompt.startswith("<agent_instructions>")
    assert "<identity>" in prompt
    assert "Use independently useful search queries" in prompt
    assert "Avoid duplicate queries" in prompt
    assert "Do not search again once evidence is sufficient" in prompt
    assert "Core TM lending integration" in prompt
    assert "Do not invent unsupported enterprise facts" in prompt
    assert "Do not expose private chain-of-thought" in prompt
    assert "intent classification" not in prompt
    assert "final synthesis" not in prompt


def test_specialized_prompts_stay_isolated_from_agent_loop_rules() -> None:
    capability = render_prompt("capability_base")
    compression = render_prompt("conversation_compression")

    assert "conversational agent" in capability
    assert "retrieval" not in capability
    assert "Preserve user goals" in compression
    assert "user-facing summary" in compression
