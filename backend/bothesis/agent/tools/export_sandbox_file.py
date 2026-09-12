"""Promote an observed sandbox file into a durable conversation artifact."""

from __future__ import annotations

from bothesis.agent.models import ToolResult
from bothesis.agent.tools import Tool, ToolInvocation, ToolSpec
from bothesis.services import ArtifactValidationError


class ExportSandboxFile(Tool):
    """Export a sandbox output only when the agent deliberately requests it."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="export_sandbox_file",
            description=(
                "Export one file reported by the hosted shell as a durable conversation "
                "artifact. Use this only for a useful final or intermediate deliverable. "
                "The file_name must exactly match a shell-reported workspace file."
            ),
            input_schema={
                "type": "object",
                "properties": {"file_name": {"type": "string", "minLength": 1}},
                "required": ["file_name"],
                "additionalProperties": False,
            },
            activity_label="Save workspace file",
            requires_sandbox=True,
        )

    async def handle(self, invocation: ToolInvocation) -> ToolResult:
        sandbox = invocation.session.sandbox
        if sandbox is None:
            return ToolResult(
                content="",
                error="Hosted workspace is unavailable.",
                metadata={"outcome": "unavailable", "result_count": 0},
            )
        try:
            artifact = await sandbox.promote_file(
                str(invocation.payload.arguments["file_name"]),
                summary="Exported from the hosted workspace.",
            )
        except ArtifactValidationError as exc:
            return ToolResult(
                content="",
                error=str(exc),
                metadata={"outcome": "invalid_input", "result_count": 0},
            )
        await invocation.report_progress(
            "artifact",
            {
                "artifact": {
                    "id": artifact.id,
                    "title": artifact.title,
                    "file_name": artifact.name,
                    "mime_type": artifact.mime_type,
                    "revision": artifact.revision,
                    "size_bytes": artifact.size_bytes,
                    "updated_at": artifact.updated_at or "",
                }
            },
        )
        return ToolResult(
            content=(
                f"Saved {artifact.name} as a conversation artifact (revision "
                f"{artifact.revision})."
            ),
            metadata={"outcome": "success", "result_count": 1},
        )


__all__ = ["ExportSandboxFile"]
