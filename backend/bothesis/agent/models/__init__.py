"""Shared, framework-free contracts for the enterprise agent loop."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from bothesis.agent.protocol import FunctionCallItem
from bothesis.knowledge import Evidence


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """A bounded prior turn supplied by the client for model context."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ConversationDocument:
    """Server-validated Document context available to one model run."""

    id: str
    title: str
    content_type: str
    mode: Literal["direct", "indexed"]
    citation_id: str
    content_block: Mapping[str, Any] | None = None
    extracted_text: str | None = None
    evidence: tuple[Evidence, ...] = ()
    provider_annotations: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationArtifact:
    """A document the agent created or revised for the user.

    It travels two ways. On :attr:`AgentContext.artifacts` it is the working
    set of this conversation, with a bounded ``content`` so the model can make
    precise edits. On :attr:`ToolOutput.artifacts` it is the revision a tool
    just produced, without content, which the stream projects onto the answer
    as a ``bothesis:artifact`` annotation.
    """

    id: str
    title: str
    file_name: str
    mime_type: str
    revision: int
    size_bytes: int
    updated_at: str
    exports: tuple[str, ...] = ()
    content: str | None = None
    content_truncated: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ConversationArtifact:
        """Build the reference an artifact service payload describes."""

        exports = payload.get("exports")
        return cls(
            id=str(payload["id"]),
            title=str(payload["title"]),
            file_name=str(payload["file_name"]),
            mime_type=str(payload["mime_type"]),
            revision=int(payload["revision"]),
            size_bytes=int(payload["size_bytes"]),
            updated_at=str(payload["updated_at"]),
            exports=tuple(sorted(exports)) if isinstance(exports, Mapping) else (),
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
            "exports": list(self.exports),
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
    documents: tuple[ConversationDocument, ...] = ()
    artifacts: tuple[ConversationArtifact, ...] = ()
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
class ToolContext:
    """Authenticated runtime context supplied to one tool execution."""

    agent_context: AgentContext
    references: CitationReferences = field(default_factory=CitationReferences)


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """A tool result before the runtime binds it to a provider call ID."""

    content: str
    evidence: list[Evidence] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    artifacts: tuple[ConversationArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolObservation:
    """One model invocation paired with the outcome observed by the runtime."""

    call: FunctionCallItem
    output: ToolOutput
    duration_ms: int

    @property
    def result_count(self) -> int | None:
        value = self.output.metadata.get("result_count")
        return value if isinstance(value, int) else None

    @property
    def status(self) -> Literal["completed", "failed", "timeout", "skipped"]:
        if not self.output.error:
            return "completed"
        outcome = self.output.metadata.get("outcome")
        if outcome == "timeout":
            return "timeout"
        if outcome in {"duplicate_call", "tool_call_limit"}:
            return "skipped"
        return "failed"


@dataclass(slots=True)
class ConversationRun:
    """Mutable accounting and grounded evidence for one user-initiated run."""

    user_message: str
    model_iteration: int = 0
    tool_round: int = 0
    tool_call_count: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    tool_context_characters: int = 0
    answer_character_count: int = 0
    evidence: dict[str, Evidence] = field(default_factory=dict)
    used_evidence_ids: set[str] = field(default_factory=set)
    executed_tool_signatures: set[str] = field(default_factory=set)
    references: CitationReferences = field(default_factory=CitationReferences)
    artifacts: dict[str, ConversationArtifact] = field(default_factory=dict)


__all__ = [
    "AgentContext",
    "CitationReferences",
    "ConversationArtifact",
    "ConversationDocument",
    "ConversationMessage",
    "ConversationRun",
    "Evidence",
    "ToolContext",
    "ToolObservation",
    "ToolOutput",
]
