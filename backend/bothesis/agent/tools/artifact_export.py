"""Export the current revision of a conversation artifact."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bothesis.agent.models import ConversationArtifact, ToolContext, ToolOutput
from bothesis.agent.tools import (
    Tool,
    ToolDefinition,
    artifact_observation,
    safe_tool_failure,
    uuid_or_none,
)

if TYPE_CHECKING:
    from bothesis.services.artifact import ArtifactService

_FORMATS = ("pdf",)


class ArtifactExport(Tool):
    """Render the current revision to a download format inside the sandbox."""

    def __init__(self, artifacts: ArtifactService) -> None:
        self._artifacts = artifacts
        self._definition = ToolDefinition(
            name="artifact_export",
            description=(
                "Export the current revision of an artifact of this conversation to "
                "a file format the user asked for. The export is attached to the "
                "document card; it does not change the document."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The artifact to export.",
                    },
                    "format": {
                        "type": "string",
                        "enum": list(_FORMATS),
                        "description": "The export format.",
                    },
                },
                "required": ["artifact_id", "format"],
                "additionalProperties": False,
            },
            activity_label="Export document",
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        artifact_id = uuid_or_none(arguments.get("artifact_id"))
        export_format = arguments.get("format")
        if artifact_id is None:
            return _invalid("artifact_id must be the id of an artifact in this conversation.")
        if export_format not in _FORMATS:
            return _invalid(f"format must be one of: {', '.join(_FORMATS)}.")
        try:
            access = await self._artifacts.resolve_access(ctx.agent_context)
            payload = await self._artifacts.export(access, artifact_id, format=export_format)
        except Exception as exc:  # noqa: BLE001 - mapped to an observation
            failure = safe_tool_failure(exc)
            if failure is None:
                raise
            return failure
        reference = ConversationArtifact.from_payload(payload)
        return artifact_observation(
            reference,
            action=f"Exported document to {export_format.upper()}",
            content=None,
            max_characters=0,
            guidance=(
                "Tell the user the export is ready to download from the document card."
            ),
        )


def _invalid(message: str) -> ToolOutput:
    return ToolOutput(
        content="",
        error=message,
        metadata={"outcome": "invalid_input", "result_count": 0, "duration_ms": 0},
    )


__all__ = ["ArtifactExport"]
