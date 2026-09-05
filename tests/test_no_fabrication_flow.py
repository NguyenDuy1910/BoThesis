"""Test cases to verify enhanced anti-fabrication rules in agent flow."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.prompts.template_render import render_agent_base


def test_agent_base_includes_no_fabrication_rule() -> None:
    """Verify agent_base.md includes explicit no-fabrication rules."""
    prompt = render_agent_base()

    # Core anti-fabrication rules
    assert "<no_fabrication_rule>" in prompt
    assert "Never fabricate, guess, or invent answers" in prompt
    assert "I could not find this information in the knowledge base" in prompt
    assert "Never provide speculation" in prompt

    # Clarification rule for vague questions
    assert "<clarification_rule>" in prompt
    assert "When a user's question is too vague" in prompt
    assert "Ask clarifying questions FIRST before attempting any search" in prompt

    # Knowledge base requirement
    assert "<knowledge_base_requirement>" in prompt
    assert "All enterprise-related questions MUST be grounded in the knowledge base" in prompt

    # Enhanced tool_use guidance
    assert "Answer directly ONLY when" in prompt
    assert "Use enterprise retrieval (knowledge_search) when" in prompt

    # Evidence decision enhancement
    assert "If knowledge_search returns NO RESULTS" in prompt
    assert "explicitly tell the user this fact" in prompt

    # Response hierarchy
    assert "<response_hierarchy>" in prompt
    assert "Is this an enterprise question?" in prompt
    assert "Is the question vague/needs clarification?" in prompt
    assert "If no evidence found → explicitly state" in prompt


def test_vague_vietnamese_query_expected_behavior() -> None:
    """
    Document expected behavior for query: "cho tôi template mẫu đăng ký môn học"
    Translation: "give me a template for course registration"

    This is a good test case because:
    1. It's enterprise-specific (course registration is internal process)
    2. It's vague (no details about which system, which format, etc.)
    3. Agent should either:
       a) Ask for clarification (preferred by new rules)
       b) Search knowledge base and report if nothing found (not fabricate)
    """
    prompt = render_agent_base()

    # Verify the prompt includes rules for handling vague queries
    assert "too vague or not specific enough" in prompt
    assert "Ask clarifying questions FIRST" in prompt
    assert "Request specific details: entity names, dates, business areas" in prompt

    # Verify no-speculation rule
    assert 'Never provide speculation or "likely" answers about enterprise facts' in prompt


def test_knowledge_search_empty_result_handling() -> None:
    """
    Verify knowledge_search tool description includes guidance for empty results.
    When query returns no results, agent must explicitly state this.
    """
    prompt = render_agent_base()

    # Check for explicit empty result handling
    assert "If knowledge_search returns NO RESULTS" in prompt
    assert "explicitly tell the user this fact" in prompt
    assert "rather than providing speculation or unsourced answers" in prompt


def test_response_hierarchy_for_enterprise_questions() -> None:
    """Verify response hierarchy prioritizes verification over fabrication."""
    prompt = render_agent_base()

    hierarchy = prompt[prompt.find("<response_hierarchy>") : prompt.find("</response_hierarchy>")]

    # Check order of decision-making
    assert hierarchy.find("Is this an enterprise question?") < hierarchy.find(
        "Is the question vague"
    )
    assert hierarchy.find("search knowledge base first") < hierarchy.find(
        "Do I have sufficient grounded evidence"
    )
    assert hierarchy.find("If no evidence found") < hierarchy.find(
        "Never jump to speculation"
    )


def test_grounding_section_enhanced() -> None:
    """Verify grounding section is enhanced to prevent fabrication."""
    prompt = render_agent_base()

    grounding_section = prompt[prompt.find("<grounding>") : prompt.find("</grounding>")]

    assert "Do not invent unsupported enterprise facts" in grounding_section
    assert "If you cannot ground a claim" in grounding_section
    assert "Do NOT provide it as fact" in grounding_section
    assert "This is not in the knowledge base" in grounding_section


def test_search_guidance_warns_against_vague_terms() -> None:
    """Verify search guidance explicitly warns against vague search terms."""
    prompt = render_agent_base()

    assert "Vague searches that may return irrelevant results" in prompt
    assert "Too generic: \"information\", \"details\", \"data\"" in prompt
    assert "Before searching with vague terms, ASK FOR CLARIFICATION" in prompt


if __name__ == "__main__":
    # Run all tests
    test_agent_base_includes_no_fabrication_rule()
    print("✓ Agent base includes no-fabrication rules")

    test_vague_vietnamese_query_expected_behavior()
    print("✓ Vague query handling verified")

    test_knowledge_search_empty_result_handling()
    print("✓ Empty result handling verified")

    test_response_hierarchy_for_enterprise_questions()
    print("✓ Response hierarchy verified")

    test_grounding_section_enhanced()
    print("✓ Grounding section enhanced")

    test_search_guidance_warns_against_vague_terms()
    print("✓ Search guidance enhanced")

    print("\n✅ All anti-fabrication enhancements verified!")
