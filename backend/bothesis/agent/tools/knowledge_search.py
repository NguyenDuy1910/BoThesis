"""Permission boundary for enterprise knowledge retrieval."""

from __future__ import annotations

from typing import Any

from bothesis.agent.models import AgentContext, ToolResult
from bothesis.agent.tools import AgentTool


class KnowledgeSearchTool(AgentTool):
    """Retrieve permission-filtered enterprise evidence.

    A retrieval adapter has not been configured in this scaffold. Returning an
    explicit unavailable observation is safer than inventing enterprise
    documents or citations.
    """

    name = "knowledge_search"
    description = "Search permission-approved enterprise knowledge for evidence."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The enterprise knowledge question to search for.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    async def execute(self, arguments: dict[str, Any], ctx: AgentContext) -> ToolResult:
        if not ctx.tenant_id or not ctx.user_id or not ctx.roles:
            return ToolResult(
                call_id="",
                content="",
                error="Knowledge search requires tenant, user, and role context.",
            )
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(call_id="", content="", error="knowledge_search requires a non-empty query.")
        return ToolResult(
            call_id="",
            content="",
            error="Knowledge retrieval is not configured for this deployment.",
        )
