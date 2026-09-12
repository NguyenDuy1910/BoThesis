"""Invariant grounding checks for the small, stable agent prompt."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis import render_agent_base


def test_agent_base_requires_observed_grounded_evidence() -> None:
    prompt = render_agent_base()

    assert "Do not claim enterprise facts that have" in prompt
    assert "not been observed in grounded evidence" in prompt
    assert "say so plainly rather than guessing" in prompt


def test_agent_base_keeps_workflows_out_of_core_instructions() -> None:
    prompt = render_agent_base()

    assert "knowledge_search" not in prompt
    assert "read_resource" not in prompt
    assert "if PDF" not in prompt
