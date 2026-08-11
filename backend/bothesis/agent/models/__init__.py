"""Shared, framework-free contracts for the enterprise agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Literal, TypeAlias


class ExecutionMode(StrEnum):
    """Top-level route selected for an agent request."""

    DIRECT = "direct"
    PLANNED = "planned"


class AssistantPhase(StrEnum):
    """Public phases that can contribute to one assistant turn."""

    COMMENTARY = "commentary"
    TOOL_ACTIVITY = "tool_activity"
    INTERMEDIATE_FINDING = "intermediate_finding"
    FINAL_ANSWER = "final_answer"


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


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Source metadata that is safe and useful to send to the chat client."""

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
class AgentContext:
    """The authenticated scope for a single agent request."""

    user_id: str
    tenant_id: str
    roles: list[str]
    conversation_id: str | None = None
    request_id: str | None = None
    history: tuple[ConversationMessage, ...] = ()
    trace_step: int | None = None
    retrieval_round: int = 0
    retrieval_query_count: int = 0


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    content: str
    evidence: list[Evidence] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepResult:
    """One planned step's bounded execution outcome."""

    step_id: str
    title: str
    tool_name: str | None
    result: ToolResult | None
    success: bool
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    finish_reason: str | None
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


# Internal transport stream events. These are never sent directly to clients.
@dataclass(frozen=True, slots=True)
class TextDelta:
    delta: str


@dataclass(frozen=True, slots=True)
class ProviderReasoningDelta:
    """An official provider-supplied reasoning summary fragment.

    Provider adapters must never populate this event from raw reasoning text.
    """

    delta: str


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class TurnDone:
    finish_reason: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


# SSE events. ``type`` is deliberately a class variable; the HTTP layer adds
# it while serializing the dataclass payload. Sequence metadata is public and
# deliberately excluded from equality so existing event-level tests remain
# focused on behavior rather than transport decoration.
@dataclass(frozen=True, slots=True, kw_only=True)
class StreamEvent:
    sequence: int = field(default=0, compare=False)
    event_id: str = field(default="", compare=False)


@dataclass(frozen=True, slots=True)
class RunStarted(StreamEvent):
    type: ClassVar[str] = "run_started"
    conversation_id: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class TurnStarted(StreamEvent):
    type: ClassVar[str] = "turn_started"
    turn: int


GenerationKind: TypeAlias = Literal["next_step", "final_response"]


@dataclass(frozen=True, slots=True)
class GenerationStarted(StreamEvent):
    type: ClassVar[str] = "generation_started"
    turn: int


@dataclass(frozen=True, slots=True)
class GenerationCompleted(StreamEvent):
    type: ClassVar[str] = "generation_completed"
    turn: int
    generation_kind: GenerationKind
    finish_reason: str | None
    tool_call_count: int
    selected_tools: list[str]
    duration_ms: int


@dataclass(frozen=True, slots=True)
class MessageDelta(StreamEvent):
    type: ClassVar[str] = "message_delta"
    text: str


@dataclass(frozen=True, slots=True)
class PublicReasoningStarted(StreamEvent):
    type: ClassVar[str] = "public_reasoning_started"
    turn: int


@dataclass(frozen=True, slots=True)
class PublicReasoningDelta(StreamEvent):
    type: ClassVar[str] = "public_reasoning_delta"
    turn: int
    text: str


@dataclass(frozen=True, slots=True)
class PublicReasoningCompleted(StreamEvent):
    type: ClassVar[str] = "public_reasoning_completed"
    turn: int


@dataclass(frozen=True, slots=True)
class ProviderReasoningSummaryDelta(StreamEvent):
    type: ClassVar[str] = "provider_reasoning_summary_delta"
    turn: int
    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted(StreamEvent):
    type: ClassVar[str] = "tool_started"
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCompleted(StreamEvent):
    type: ClassVar[str] = "tool_completed"
    call_id: str
    name: str
    error: str | None = None
    duration_ms: int | None = None
    result_count: int | None = None


@dataclass(frozen=True, slots=True)
class CitationAvailable(StreamEvent):
    type: ClassVar[str] = "citation_available"
    evidence: EvidenceReference


@dataclass(frozen=True, slots=True)
class CitationEvent(StreamEvent):
    type: ClassVar[str] = "citation"
    evidence_id: str
    title: str
    page: str | None = None
    uri: str | None = None


@dataclass(frozen=True, slots=True)
class TurnCompleted(StreamEvent):
    type: ClassVar[str] = "turn_completed"
    turn: int
    outcome: Literal["tool", "final"]


@dataclass(frozen=True, slots=True)
class RunCompleted(StreamEvent):
    type: ClassVar[str] = "run_completed"
    duration_ms: int | None = None
    model_duration_ms: int | None = None
    tool_duration_ms: int | None = None
    tool_call_count: int | None = None


@dataclass(frozen=True, slots=True)
class RunFailed(StreamEvent):
    type: ClassVar[str] = "run_failed"
    error: str


@dataclass(frozen=True, slots=True)
class CommentaryDelta(StreamEvent):
    type: ClassVar[str] = "commentary_delta"
    text: str


@dataclass(frozen=True, slots=True)
class IntermediateFindingDelta(StreamEvent):
    type: ClassVar[str] = "intermediate_finding_delta"
    text: str


@dataclass(frozen=True, slots=True)
class FinalAnswerDelta(StreamEvent):
    type: ClassVar[str] = "final_answer_delta"
    text: str


@dataclass(frozen=True, slots=True)
class InterleavedToolStarted(StreamEvent):
    """Safe public tool activity without arguments or provider call IDs."""

    type: ClassVar[str] = "tool_started"
    activity_id: str
    label: str
    category: Literal["retrieval", "tool"]
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class InterleavedToolCompleted(StreamEvent):
    type: ClassVar[str] = "tool_completed"
    activity_id: str
    label: str
    category: Literal["retrieval", "tool"]
    status: Literal["completed", "failed", "timeout", "skipped"]
    attempt: int = 1
    duration_ms: int | None = None
    result_count: int | None = None
    message: str | None = None


AgentEvent: TypeAlias = (
    RunStarted
    | TurnStarted
    | GenerationStarted
    | GenerationCompleted
    | MessageDelta
    | PublicReasoningStarted
    | PublicReasoningDelta
    | PublicReasoningCompleted
    | ProviderReasoningSummaryDelta
    | ToolStarted
    | ToolCompleted
    | CitationAvailable
    | CitationEvent
    | TurnCompleted
    | RunCompleted
    | RunFailed
    | CommentaryDelta
    | IntermediateFindingDelta
    | FinalAnswerDelta
    | InterleavedToolStarted
    | InterleavedToolCompleted
)

__all__ = [
    "AgentContext",
    "AgentEvent",
    "AssistantPhase",
    "CitationAvailable",
    "CitationEvent",
    "CommentaryDelta",
    "ConversationMessage",
    "Evidence",
    "EvidenceReference",
    "ExecutionMode",
    "FinalAnswerDelta",
    "GenerationCompleted",
    "GenerationKind",
    "GenerationStarted",
    "MessageDelta",
    "ModelTurn",
    "IntermediateFindingDelta",
    "InterleavedToolCompleted",
    "InterleavedToolStarted",
    "ProviderReasoningDelta",
    "ProviderReasoningSummaryDelta",
    "PublicReasoningCompleted",
    "PublicReasoningDelta",
    "PublicReasoningStarted",
    "RunCompleted",
    "RunFailed",
    "RunStarted",
    "StepResult",
    "StreamEvent",
    "TextDelta",
    "ToolCall",
    "ToolCallDelta",
    "ToolCompleted",
    "ToolResult",
    "ToolStarted",
    "TurnCompleted",
    "TurnDone",
    "TurnStarted",
]
