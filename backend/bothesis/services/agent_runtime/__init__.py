"""Request-scoped service adapters used exclusively by the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass

from bothesis.knowledge import Evidence

MAX_KNOWLEDGE_SEARCH_QUERY_CHARACTERS = 512


@dataclass(frozen=True, slots=True)
class AgentKnowledgeSearchResult:
    """The bounded, citable outcome of one agent knowledge-search request."""

    content: str
    evidence: tuple[Evidence, ...] = ()
    error: str | None = None
    outcome: str = "success"
    success_criteria_met: bool | None = None
    duration_ms: int = 0
