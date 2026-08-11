"""Observable state for one enterprise knowledge-agent request."""

from __future__ import annotations

from dataclasses import dataclass, field

from bothesis.agent.models import Evidence


@dataclass(slots=True)
class KnowledgeAgentState:
    """Useful request state only; never stores private model reasoning."""

    user_message: str
    search_queries: list[str] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    executed_tool_signatures: set[str] = field(default_factory=set)
    used_evidence_ids: set[str] = field(default_factory=set)
    tool_round: int = 0
    retrieval_round: int = 0
    completion_status: str = "running"
    step: int = 0
    model_turn_count: int = 0
    tool_call_count: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    tool_context_characters: int = 0
    answer_character_count: int = 0


__all__ = ["KnowledgeAgentState"]
