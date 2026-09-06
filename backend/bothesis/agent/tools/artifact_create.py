"""Start a new conversation artifact from a source document or from written content."""

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
                "Provide EITHER source_document_id (the Document ID of a document "
                "found via knowledge_search or listed in the conversation document "
                "references, for example a template or form) to start this "
                "artifact as an editable working copy of that document, OR "
                "content (the complete document in Markdown) to write a new one; "
                "set the other to null. Every readable source format works, "
                "including PDF: a fillable PDF form keeps its original layout and "
                "is filled field by field with artifact_edit, and other documents "
                "become editable text — never rewrite a source document yourself "
                "instead of passing its Document ID. Creating an artifact never "
                "modifies the source document. Enterprise facts written into a "
                "document must come from knowledge_search results or the "
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
                    "source_document_id": {
                        "type": ["string", "null"],
                        "description": (
                            "The Document ID of a source document from a "
                            "knowledge_search result, or null when writing the "
                            "document from content instead."
                        ),
                    },
                    "content": {
                        "type": ["string", "null"],
                        "maxLength": max_content_characters,
                        "description": (
                            "The complete document in Markdown, or null when "
                            "starting from source_document_id."
                        ),
                    },
                },
                "required": ["title", "source_document_id", "content"],
                "additionalProperties": False,
            },
            activity_label="Create document",
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        title = arguments.get("title")
        source_document_id = arguments.get("source_document_id")
        content = arguments.get("content")
        if not isinstance(title, str) or not title.strip():
            return _invalid("artifact_create requires a title.")
        if (source_document_id is None) == (content is None):
            return _invalid(
                "artifact_create needs exactly one of source_document_id or content."
            )
        source_id = (
            uuid_or_none(source_document_id) if source_document_id is not None else None
        )
        if source_document_id is not None and source_id is None:
            return _invalid(
                "source_document_id must be the Document ID of a document found "
                "via knowledge_search."
            )

        scope = ctx.agent_context
        try:
            access = await self._artifacts.resolve_access(scope)
            if source_id is not None:
                payload = await self._artifacts.create_from_document(
                    access,
                    title=title,
                    source_document_id=source_id,
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
            # A source document's text is new to the model; content it wrote itself is not.
            content=payload.get("content") if source_id is not None else None,
            max_characters=self._max_result_characters,
            guidance=_creation_guidance(reference) if source_id is not None else None,
        )


def _creation_guidance(reference: ConversationArtifact) -> str:
    if reference.mime_type == "application/pdf":
        return (
            "This is the original PDF with its layout preserved. Fill its form "
            "fields with artifact_edit(fields=...) using the exact field names "
            "in the content, grounded in the conversation or knowledge_search; "
            "leave fields you cannot ground empty and tell the user which ones "
            "still need their input."
        )
    return (
        "Fill the document in with artifact_edit using facts from the "
        "conversation or knowledge_search; leave placeholders you cannot "
        "ground and tell the user."
    )


def _invalid(message: str) -> ToolOutput:
    return ToolOutput(
        content="",
        error=message,
        metadata={"outcome": "invalid_input", "result_count": 0, "duration_ms": 0},
    )


__all__ = ["ArtifactCreate"]
