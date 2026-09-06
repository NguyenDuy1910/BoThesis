"""Revise an existing conversation artifact as a new revision."""

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


class ArtifactEdit(Tool):
    """Apply find/replace edits, a rewrite, or PDF form fills; the sandbox
    produces the file."""

    _MAX_EDITS = 50
    _MAX_FIELDS = 100

    def __init__(
        self,
        artifacts: ArtifactService,
        *,
        max_content_characters: int = 200_000,
        max_result_characters: int = 8_000,
    ) -> None:
        if min(max_content_characters, max_result_characters) < 1:
            raise ValueError("artifact_edit limits must be at least one")
        self._artifacts = artifacts
        self._max_result_characters = max_result_characters
        self._definition = ToolDefinition(
            name="artifact_edit",
            description=(
                "Revise an existing artifact of this conversation (its id and "
                "current content are in the conversation artifacts context or in "
                "a previous artifact result). For a text document, prefer targeted "
                "edits: each find must match the current content exactly once and "
                "is replaced by replace; use content for a complete rewrite only "
                "when most of the document changes. For a fillable PDF document "
                "(its content lists its form fields), use fields instead: the "
                "exact field names with the values to write — the original PDF "
                "layout is preserved and edits/content do not apply. Provide "
                "exactly one of edits, content, or fields; set the unused ones to "
                "null or an empty list. Every call creates a new revision of the "
                "SAME artifact; never create a second artifact for a follow-up "
                "change."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The artifact to revise.",
                    },
                    "summary": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                        "description": "One sentence describing what changed.",
                    },
                    "edits": {
                        "type": "array",
                        "description": (
                            "Exact find/replace pairs applied to the current "
                            "content. Include enough surrounding text for each find "
                            "to be unique. Empty when content is given."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "find": {"type": "string", "minLength": 1},
                                "replace": {"type": "string"},
                            },
                            "required": ["find", "replace"],
                            "additionalProperties": False,
                        },
                        "maxItems": self._MAX_EDITS,
                    },
                    "content": {
                        "type": ["string", "null"],
                        "maxLength": max_content_characters,
                        "description": (
                            "The complete new document in Markdown for a rewrite, "
                            "or null when using edits or fields."
                        ),
                    },
                    "fields": {
                        "type": ["array", "null"],
                        "description": (
                            "For a fillable PDF artifact only: the form fields to "
                            "set, using the exact field names from the artifact's "
                            "field list. A button or choice field accepts only "
                            "one of its listed states. Null for text documents."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "minLength": 1},
                                "value": {"type": "string"},
                            },
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                        "maxItems": self._MAX_FIELDS,
                    },
                },
                "required": ["artifact_id", "summary", "edits", "content", "fields"],
                "additionalProperties": False,
            },
            activity_label="Edit document",
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        artifact_id = uuid_or_none(arguments.get("artifact_id"))
        summary = arguments.get("summary")
        edits = arguments.get("edits")
        content = arguments.get("content")
        raw_fields = arguments.get("fields")
        if artifact_id is None:
            return _invalid("artifact_id must be the id of an artifact in this conversation.")
        if not isinstance(summary, str) or not summary.strip():
            return _invalid("artifact_edit requires a summary of the change.")
        if not isinstance(edits, list):
            return _invalid("edits must be a list of find/replace pairs.")
        fields, fields_error = _validated_fields(raw_fields)
        if fields_error is not None:
            return _invalid(fields_error)
        if sum((bool(edits), content is not None, fields is not None)) != 1:
            return _invalid(
                "artifact_edit needs exactly one of edits, content, or fields."
            )

        scope = ctx.agent_context
        try:
            access = await self._artifacts.resolve_access(scope)
            payload = await self._artifacts.edit(
                access,
                artifact_id,
                summary=summary,
                edits=[
                    {"find": str(edit.get("find", "")), "replace": str(edit.get("replace", ""))}
                    for edit in edits
                    if isinstance(edit, dict)
                ],
                content=str(content) if content is not None else None,
                fields=fields,
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
            action="Revised document",
            content=payload.get("content"),
            max_characters=self._max_result_characters,
            guidance=(
                "Summarize what changed for the user; the updated document is "
                "shown to them as a card, so do not repeat it."
            ),
        )


def _validated_fields(value: Any) -> tuple[dict[str, str] | None, str | None]:
    """Turn the fields argument into a name→value map, or explain what's wrong.

    An absent or empty list means "not using fields", mirroring how edits are
    treated, so a model sending fields=[] alongside edits is not rejected.
    """

    if value is None or value == []:
        return None, None
    if not isinstance(value, list):
        return None, "fields must be a list of {name, value} objects."
    fields: dict[str, str] = {}
    for position, entry in enumerate(value, start=1):
        if not isinstance(entry, dict):
            return None, f"field {position} must be an object with name and value."
        name = entry.get("name")
        field_value = entry.get("value")
        if not isinstance(name, str) or not name.strip():
            return None, f"field {position}: name must be non-empty text."
        if not isinstance(field_value, str):
            return None, f"field {position}: value must be text."
        if name in fields:
            return None, f"field {position}: duplicate name {name!r}."
        fields[name] = field_value
    return fields, None


def _invalid(message: str) -> ToolOutput:
    return ToolOutput(
        content="",
        error=message,
        metadata={"outcome": "invalid_input", "result_count": 0, "duration_ms": 0},
    )


__all__ = ["ArtifactEdit"]
