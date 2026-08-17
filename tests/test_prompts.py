from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.prompts.template_render import (
    PromptRenderError,
    load_prompt,
    render_base_instruction,
)


def test_prompt_set_has_only_the_base_instruction_role() -> None:
    prompt_directory = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "bothesis"
        / "agent"
        / "prompts"
    )
    prompt_names = {path.stem for path in prompt_directory.glob("*.md")}

    assert prompt_names == {"base_instruction"}
    assert "relevant conversation" in load_prompt("base_instruction")


def test_renderer_rejects_invalid_prompt_names() -> None:
    with pytest.raises(PromptRenderError, match="invalid prompt name"):
        load_prompt("../system")


def test_base_instruction_defines_lightweight_retrieval_and_grounding_guidance() -> None:
    prompt = render_base_instruction()

    assert prompt.startswith("You are BoThesis")
    assert "Use independently useful search queries" in prompt
    assert "Avoid duplicate queries" in prompt
    assert "Do not search again once evidence is sufficient" in prompt
    assert "Core TM lending integration" in prompt
    assert "Do not invent unsupported enterprise facts" in prompt
    assert "Do not expose private chain-of-thought" in prompt
    assert "intent classification" not in prompt
    assert "final synthesis" not in prompt
