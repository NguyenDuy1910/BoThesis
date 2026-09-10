"""Expose bounded, citable enterprise retrieval to the model."""

from __future__ import annotations

from bothesis.agent.models import ToolResult
from bothesis.agent.tools import Tool, ToolInvocation, ToolSpec
from bothesis.knowledge import ContextBuilder, KnowledgeRetriever
from bothesis.observability import Tracer
from bothesis.services.agent_runtime import MAX_KNOWLEDGE_SEARCH_QUERY_CHARACTERS
from bothesis.services.agent_runtime.knowledge_search import AgentKnowledgeSearchService


class KnowledgeSearch(Tool):
    """Translate the model tool contract into agent-runtime retrieval."""

    _MAX_QUERY_CHARACTERS = MAX_KNOWLEDGE_SEARCH_QUERY_CHARACTERS

    def __init__(
        self,
        retriever: KnowledgeRetriever,
        *,
        result_limit: int = 5,
        max_queries: int = 3,
        timeout_seconds: float = 25.0,
        max_context_characters: int = 8_000,
        max_evidence_characters: int = 1_600,
        context_builder: ContextBuilder | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._max_queries = max_queries
        self._search = AgentKnowledgeSearchService(
            retriever,
            result_limit=result_limit,
            max_queries=max_queries,
            timeout_seconds=timeout_seconds,
            max_context_characters=max_context_characters,
            max_evidence_characters=max_evidence_characters,
            context_builder=context_builder,
            tracer=tracer,
        )
        self._definition = self._build_definition()

    def spec(self) -> ToolSpec:
        return self._definition

    def _build_definition(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_search",
            description=(
                "Search access-permitted enterprise sources for grounded evidence. "
                "Use it when the answer needs organization-specific facts or the user "
                "asks to search knowledge. Supply one to three focused, standalone "
                "queries. It returns citable evidence with a source reference to cite "
                "or reports that no permitted source was found."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "description": (
                            "Focused, independently useful queries. Do not use generic "
                            "terms without available scope; include names, identifiers, "
                            "dates, or other useful detail."
                        ),
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": self._MAX_QUERY_CHARACTERS,
                        },
                        "minItems": 1,
                        "maxItems": self._max_queries,
                    }
                },
                "required": ["queries"],
                "additionalProperties": False,
            },
            activity_label="Search knowledge base",
            activity_category="retrieval",
        )

    async def handle(self, invocation: ToolInvocation) -> ToolResult:
        result = await self._search.search(
            invocation.payload.arguments,
            context=invocation.agent_context,
            references=invocation.references,
            call_id=invocation.call_id,
        )
        metadata: dict[str, str | int | bool] = {
            "outcome": result.outcome,
            "result_count": len(result.evidence),
            "duration_ms": result.duration_ms,
        }
        if result.success_criteria_met is not None:
            metadata["success_criteria_met"] = result.success_criteria_met
        return ToolResult(
            content=result.content,
            evidence=list(result.evidence),
            error=result.error,
            metadata=metadata,
        )


__all__ = ["KnowledgeSearch"]
