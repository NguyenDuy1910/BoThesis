"""Make one authorized resource available to a hosted sandbox shell."""

from __future__ import annotations

from bothesis.agent.models import ToolResult
from bothesis.agent.tools import Tool, ToolInvocation, ToolSpec
from bothesis.services import ArtifactValidationError


class MaterializeSandboxResource(Tool):
    """Explicitly copy an accessible Item into the provider-managed workspace."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="materialize_sandbox_resource",
            description=(
                "Make an available file accessible to the hosted shell on the next "
                "sampling step. Use this before shell work that needs the file. It "
                "does not read the file into the chat or expose storage paths."
            ),
            input_schema={
                "type": "object",
                "properties": {"resource_id": {"type": "string", "minLength": 1}},
                "required": ["resource_id"],
                "additionalProperties": False,
            },
            activity_label="Prepare workspace file",
            requires_sandbox=True,
        )

    async def handle(self, invocation: ToolInvocation) -> ToolResult:
        resource_id = str(invocation.payload.arguments["resource_id"])
        resource = invocation.resource(resource_id)
        sandbox = invocation.session.sandbox
        if resource is None:
            return ToolResult(
                content="",
                error="Resource is not available in this turn.",
                metadata={"outcome": "not_found", "result_count": 0},
            )
        if sandbox is None:
            return ToolResult(
                content="",
                error="Hosted workspace is unavailable.",
                metadata={"outcome": "unavailable", "result_count": 0},
            )
        try:
            materialized = await sandbox.materialize_resource(resource)
        except ArtifactValidationError as exc:
            return ToolResult(
                content="",
                error=str(exc),
                metadata={"outcome": "invalid_input", "result_count": 0},
            )
        return ToolResult(
            content=(
                f"{materialized.resource.name} is prepared for the hosted shell. "
                "Use the shell on the next sampling step to inspect or transform it."
            ),
            metadata={"outcome": "success", "result_count": 1},
        )


__all__ = ["MaterializeSandboxResource"]
