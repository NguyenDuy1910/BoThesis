"""Shared, framework-free contracts for the enterprise agent loop."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from bothesis.agent.protocol import InputContent, ToolCall
from bothesis.knowledge import Evidence


if TYPE_CHECKING:
    from bothesis.agent import ResourceRef


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """A bounded prior turn supplied by the client for model context."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ConversationArtifact:
    """A durable artifact revision reference owned by ArtifactService."""

    id: str
    title: str
    file_name: str
    mime_type: str
    revision: int
    size_bytes: int
    updated_at: str
    source_document_id: str | None = None
    content: str | None = None
    content_truncated: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ConversationArtifact:
        """Build the reference an artifact service payload describes."""

        source_document_id = payload.get("source_document_id")
        return cls(
            id=str(payload["id"]),
            title=str(payload["title"]),
            file_name=str(payload["file_name"]),
            mime_type=str(payload["mime_type"]),
            revision=int(payload["revision"]),
            size_bytes=int(payload["size_bytes"]),
            updated_at=str(payload["updated_at"]),
            source_document_id=(
                str(source_document_id) if source_document_id else None
            ),
        )

    def annotation_payload(self) -> dict[str, Any]:
        """The client-facing description; never the content."""

        return {
            "id": self.id,
            "title": self.title,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "revision": self.revision,
            "size_bytes": self.size_bytes,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class AgentContext:
    """The authenticated scope for a single agent request."""

    user_id: str
    tenant_id: str
    roles: list[str]
    collection_item_ids: tuple[str, ...] = ()
    conversation_id: str | None = None
    request_id: str | None = None
    history: tuple[ConversationMessage, ...] = ()
    allowed_tool_names: tuple[str, ...] | None = None
    trace_step: int | None = None
    retrieval_round: int = 0
    retrieval_query_count: int = 0
    resources: tuple["ResourceRef", ...] = ()
    model_extra_body: Mapping[str, Any] | None = None


@dataclass(slots=True)
class CitationReferences:
    """Run-scoped reference IDs and reader-facing numbers for one turn.

    Retrieval order assigns the compact ``ref_N`` the model is allowed to cite.
    First appearance in the answer assigns the ``[n]`` the reader sees. Both are
    scoped to one run and keyed by the identity they stand for, so the same
    chunk keeps one reference across retrieval rounds and concurrent tool calls
    without any process-wide state.
    """

    _references: dict[tuple[str, str], str] = field(default_factory=dict)
    _numbers: dict[str, int] = field(default_factory=dict)

    def reference(self, item_id: str, chunk_id: str) -> str:
        """Return this chunk's model-facing reference, assigning one if new."""

        identity = (item_id, chunk_id)
        existing = self._references.get(identity)
        if existing is not None:
            return existing
        assigned = f"ref_{len(self._references) + 1}"
        self._references[identity] = assigned
        return assigned

    def number(self, reference: str) -> int:
        """Return the reader-facing number for a reference, by first use."""

        existing = self._numbers.get(reference)
        if existing is not None:
            return existing
        assigned = len(self._numbers) + 1
        self._numbers[reference] = assigned
        return assigned


@dataclass(frozen=True, slots=True)
class ToolResult:
    """A tool result before the runtime binds it to a provider call ID."""

    content: str
    evidence: list[Evidence] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    model_content: tuple[InputContent, ...] = ()


# Existing tool implementations and integrations import this name. New code
# uses ToolResult, whose extra model_content channel supports explicit native
# multimodal materialization without smuggling it through a text observation.
ToolOutput = ToolResult


@dataclass(frozen=True, slots=True)
class ToolObservation:
    """One model invocation paired with the outcome observed by the runtime."""

    call: ToolCall
    result: ToolResult
    duration_ms: int

    @property
    def result_count(self) -> int | None:
        value = self.result.metadata.get("result_count")
        return value if isinstance(value, int) else None

    @property
    def status(self) -> Literal["completed", "failed", "timeout", "skipped"]:
        if not self.result.error:
            return "completed"
        outcome = self.result.metadata.get("outcome")
        if outcome == "timeout":
            return "timeout"
        if outcome in {"duplicate_call", "tool_call_limit"}:
            return "skipped"
        return "failed"

    @property
    def output(self) -> ToolResult:
        """Compatibility name for callers that have not moved to result yet."""

        return self.result


__all__ = [
    "AgentContext",
    "CitationReferences",
    "ConversationArtifact",
    "ConversationMessage",
    "Evidence",
    "ToolObservation",
    "ToolResult",
    "ToolOutput",
]
