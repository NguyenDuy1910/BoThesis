"""Find Knowledge Base templates the user may start a document from."""

from __future__ import annotations

from contextlib import nullcontext
from time import perf_counter
from typing import TYPE_CHECKING, Any

from bothesis.agent.models import ToolContext, ToolOutput
from bothesis.agent.tools import Tool, ToolDefinition, safe_tool_failure
from bothesis.observability import LangfuseTracing

if TYPE_CHECKING:
    from bothesis.services.template import TemplateService

_EMPTY_CONTENT = (
    "No matching templates were found in the template libraries you can access. "
    "Tell the user, and offer to draft the document from scratch instead."
)


class TemplateSearch(Tool):
    """Search template libraries with the same permission scope as knowledge."""

    _MAX_QUERY_CHARACTERS = 512

    def __init__(
        self,
        templates: TemplateService,
        *,
        max_queries: int = 3,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        if max_queries < 1:
            raise ValueError("max_queries must be at least one")
        self._templates = templates
        self._max_queries = max_queries
        self._tracing = tracing
        self._definition = ToolDefinition(
            name="template_search",
            description=(
                "Search the document templates in the Knowledge Base template "
                "libraries the user can access. Use it when the user wants a "
                "document that should follow a company template (contract, memo, "
                "report, checklist, policy, letter). Returns template ids to pass "
                "to artifact_create. If nothing matches, tell the user and offer "
                "to draft the document without a template."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "description": (
                            "One to three short descriptions of the document type "
                            "wanted, for example 'non-disclosure agreement' or "
                            "'weekly status report'."
                        ),
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": self._MAX_QUERY_CHARACTERS,
                        },
                        "minItems": 1,
                        "maxItems": max_queries,
                    }
                },
                "required": ["queries"],
                "additionalProperties": False,
            },
            activity_label="Search templates",
            activity_category="retrieval",
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        raw_queries = arguments.get("queries")
        if not isinstance(raw_queries, list) or not raw_queries:
            return _invalid("template_search requires at least one query.")
        queries: list[str] = []
        for raw_query in raw_queries[: self._max_queries]:
            if not isinstance(raw_query, str):
                return _invalid("template_search queries must be strings.")
            query = " ".join(raw_query.split())[: self._MAX_QUERY_CHARACTERS]
            if query and query.casefold() not in {value.casefold() for value in queries}:
                queries.append(query)
        if not queries:
            return _invalid("template_search queries must not be empty.")

        started_at = perf_counter()
        trace_context = (
            self._tracing.tool_execution(name="template_search", arguments=arguments)
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context:
            try:
                access = await self._templates.resolve_access(ctx.agent_context)
                results = await self._templates.search(access, queries)
            except Exception as exc:  # noqa: BLE001 - mapped to an observation
                failure = safe_tool_failure(exc)
                if failure is None:
                    raise
                return failure
        duration_ms = round((perf_counter() - started_at) * 1_000)
        if not results:
            return ToolOutput(
                content=_EMPTY_CONTENT,
                metadata={"outcome": "empty", "result_count": 0, "duration_ms": duration_ms},
            )
        lines = [f"Found {len(results)} template(s):"]
        for position, result in enumerate(results, start=1):
            library = result.get("collection_title") or "template library"
            lines.append(
                f"{position}. template_id={result['id']} — \"{result['title']}\" "
                f"(library: {library})"
            )
            excerpt = " ".join(str(result.get("excerpt") or "").split())
            if excerpt:
                lines.append(f"   {excerpt}")
        lines.append(
            "Pick the best match and call artifact_create with its template_id, "
            "or ask the user which one they prefer when several fit."
        )
        return ToolOutput(
            content="\n".join(lines),
            metadata={
                "outcome": "success",
                "result_count": len(results),
                "duration_ms": duration_ms,
            },
        )


def _invalid(message: str) -> ToolOutput:
    return ToolOutput(
        content="",
        error=message,
        metadata={"outcome": "invalid_input", "result_count": 0, "duration_ms": 0},
    )


__all__ = ["TemplateSearch"]
