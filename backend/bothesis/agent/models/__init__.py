"""Shared, framework-free contracts for the enterprise agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from bothesis.agent.protocol import FunctionCallItem, FunctionCallOutputItem


@dataclass(frozen=True, slots=True)
class Evidence:
    """A source fragment available to the agent and citation UI."""

    id: str
    document_id: str
    title: str
    content: str
    page: str | None = None
    section: str | None = None
    uri: str | None = None
    source: str | None = None
    relevance_score: float | None = None


class EvidenceReference(BaseModel):
    """Source metadata that is safe and useful to send to the chat client."""

    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    title: str
    page: str | None = None
    section: str | None = None
    uri: str | None = None
    source: str | None = None
    snippet: str | None = None
    relevance_score: float | None = None


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
class AgentContext:
    """The authenticated scope for a single agent request."""

    user_id: str
    tenant_id: str
    roles: list[str]
    reader_ids: tuple[str, ...] = ()
    is_admin: bool = True
    conversation_id: str | None = None
    request_id: str | None = None
    history: tuple[ConversationMessage, ...] = ()
    trace_step: int | None = None
    retrieval_round: int = 0
    retrieval_query_count: int = 0
    documents: tuple[ConversationDocument, ...] = ()
    model_extra_body: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Authenticated runtime context supplied to one tool execution."""

    agent_context: AgentContext


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """A tool result before the runtime binds it to a provider call ID."""

    content: str
    evidence: list[Evidence] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


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

    def provider_output(self, max_characters: int) -> FunctionCallOutputItem:
        content = self.output.content
        if self.output.error:
            content = f"Tool error: {self.output.error}"
        elif not content:
            content = "Tool completed without a textual result."
        if len(content) > max_characters:
            content = f"{content[: max(1, max_characters - 1)].rstrip()}…"
        return FunctionCallOutputItem(call_id=self.call.call_id, output=content)


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


# SSE events. Every field on these models is exactly what reaches the wire:
# main.py serializes them with ``model_dump_json()`` directly, with no
# separate mapping layer. Fields that must never reach the client (tool call
# arguments) are marked ``exclude=True`` so they stay constructible for
# internal use without ever appearing in the JSON payload.
class StreamEvent(BaseModel):
    """Base for every wire-serializable application event."""

    model_config = ConfigDict(frozen=True)


class ProviderReasoningSummaryDelta(StreamEvent):
    type: Literal["provider_reasoning_summary_delta"] = "provider_reasoning_summary_delta"
    turn: int
    text: str


class ToolStarted(StreamEvent):
    type: Literal["tool_started"] = "tool_started"
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict, exclude=True)
    activity_id: str | None = None
    label: str | None = None
    category: Literal["retrieval", "tool"] | None = None


class ToolCompleted(StreamEvent):
    type: Literal["tool_completed"] = "tool_completed"
    call_id: str
    name: str
    activity_id: str | None = None
    error: str | None = None
    duration_ms: int | None = None
    result_count: int | None = None
    label: str | None = None
    category: Literal["retrieval", "tool"] | None = None
    status: Literal["completed", "failed", "timeout", "skipped"] | None = None


class CitationAvailable(StreamEvent):
    type: Literal["citation_available"] = "citation_available"
    evidence: EvidenceReference


class CitationEvent(StreamEvent):
    type: Literal["citation"] = "citation"
    evidence_id: str
    title: str
    page: str | None = None
    uri: str | None = None


class RunCompleted(StreamEvent):
    type: Literal["run_completed"] = "run_completed"
    duration_ms: int | None = None
    model_duration_ms: int | None = None
    tool_duration_ms: int | None = None
    tool_call_count: int | None = None
    provider_annotations: list[dict[str, Any]] | None = None


class RunFailed(StreamEvent):
    type: Literal["run_failed"] = "run_failed"
    error: str


class CommentaryDelta(StreamEvent):
    type: Literal["commentary_delta"] = "commentary_delta"
    text: str
    turn: int = 0


class FinalAnswerDelta(StreamEvent):
    type: Literal["final_answer_delta"] = "final_answer_delta"
    text: str


class DocumentProgress(StreamEvent):
    type: Literal["document_progress"] = "document_progress"
    document_id: str
    file_name: str
    status: Literal["preparing", "ready", "indexing", "skipped", "failed"]
    mode: Literal["direct", "indexed"]
    message: str


AgentEvent: TypeAlias = (
    ProviderReasoningSummaryDelta
    | ToolStarted
    | ToolCompleted
    | CitationAvailable
    | CitationEvent
    | RunCompleted
    | RunFailed
    | CommentaryDelta
    | FinalAnswerDelta
    | DocumentProgress
)

__all__ = [
    "AgentContext",
    "AgentEvent",
    "CitationAvailable",
    "CitationEvent",
    "CommentaryDelta",
    "ConversationRun",
    "ConversationDocument",
    "ConversationMessage",
    "Evidence",
    "EvidenceReference",
    "FinalAnswerDelta",
    "DocumentProgress",
    "ProviderReasoningSummaryDelta",
    "RunCompleted",
    "RunFailed",
    "StreamEvent",
    "ToolCompleted",
    "ToolContext",
    "ToolObservation",
    "ToolOutput",
    "ToolStarted",
]
