"""Start a new conversation artifact from a template or from written content."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

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


class ArtifactCreate(Tool):
    """Create revision 1 of a document; the sandbox writes or imports the file."""

    def __init__(
        self,
        artifacts: ArtifactService,
        *,
        max_content_characters: int = 200_000,
        max_result_characters: int = 8_000,
    ) -> None:
        if min(max_content_characters, max_result_characters) < 1:
            raise ValueError("artifact_create limits must be at least one")
        self._artifacts = artifacts
        self._max_result_characters = max_result_characters
        self._definition = ToolDefinition(
            name="artifact_create",
            description=(
                "Create a new document artifact for the user in this conversation. "
                "Provide EITHER template_id (from template_search) to start from "
                "that template, OR content (the complete document in Markdown) to "
                "write a new one; set the other to null. Enterprise facts written "
                "into a document must come from knowledge_search results or the "
                "conversation, never from guesses. Do not use this to change an "
                "existing artifact: use artifact_edit for that."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                        "description": "The document title shown to the user.",
                    },
                    "template_id": {
                        "type": ["string", "null"],
                        "description": (
                            "A template id returned by template_search, or null "
                            "when writing the document from content."
                        ),
                    },
                    "content": {
                        "type": ["string", "null"],
                        "maxLength": max_content_characters,
                        "description": (
                            "The complete document in Markdown, or null when "
                            "starting from a template."
                        ),
                    },
                },
                "required": ["title", "template_id", "content"],
                "additionalProperties": False,
            },
            activity_label="Create document",
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        title = arguments.get("title")
        template_id = arguments.get("template_id")
        content = arguments.get("content")
        if not isinstance(title, str) or not title.strip():
            return _invalid("artifact_create requires a title.")
        if (template_id is None) == (content is None):
            return _invalid(
                "artifact_create needs exactly one of template_id or content."
            )
        template_item_id = uuid_or_none(template_id) if template_id is not None else None
        if template_id is not None and template_item_id is None:
            return _invalid("template_id must be an id returned by template_search.")

        scope = ctx.agent_context
        try:
            access = await self._artifacts.resolve_access(scope)
            if template_item_id is not None:
                payload = await self._artifacts.create_from_template(
                    access,
                    title=title,
                    template_item_id=template_item_id,
                    conversation_id=uuid_or_none(scope.conversation_id),
                    request_id=scope.request_id,
                )
            else:
                payload = await self._artifacts.create_from_content(
                    access,
                    title=title,
                    content=str(content),
                    conversation_id=uuid_or_none(scope.conversation_id),
                    request_id=scope.request_id,
                )
        except Exception as exc:  # noqa: BLE001 - mapped to an observation
            failure = safe_tool_failure(exc)
            if failure is None:
                raise
            return failure
        reference = ConversationArtifact.from_payload(payload)
        return artifact_observation(
            reference,
            action="Created document",
            # A template's text is new to the model; content it wrote is not.
            content=payload.get("content") if template_item_id is not None else None,
            max_characters=self._max_result_characters,
            guidance=(
                "Fill the template in with artifact_edit using facts from the "
                "conversation or knowledge_search; leave placeholders you cannot "
                "ground and tell the user."
                if template_item_id is not None
                else None
            ),
        )


def _invalid(message: str) -> ToolOutput:
    return ToolOutput(
        content="",
        error=message,
        metadata={"outcome": "invalid_input", "result_count": 0, "duration_ms": 0},
    )


__all__ = ["ArtifactCreate"]
