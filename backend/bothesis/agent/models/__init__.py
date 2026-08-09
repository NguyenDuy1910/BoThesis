"""Shared, framework-free contracts for the enterprise agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class Evidence:
    """A permission-filtered source fragment available to the agent."""

    id: str
    document_id: str
    title: str
    content: str
    page: str | None = None
    section: str | None = None
    uri: str | None = None


@dataclass(frozen=True, slots=True)
class AgentContext:
    """The authenticated scope for a single agent request."""

    user_id: str
    tenant_id: str
    roles: list[str]
    conversation_id: str | None = None


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


@dataclass(frozen=True, slots=True)
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    finish_reason: str | None


# Internal transport stream events. These are never sent directly to clients.
@dataclass(frozen=True, slots=True)
class TextDelta:
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


# SSE events. ``type`` is deliberately a class variable; the HTTP layer adds
# it while serializing the dataclass payload.
@dataclass(frozen=True, slots=True)
class RunStarted:
    type: ClassVar[str] = "run_started"
    conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class TurnStarted:
    type: ClassVar[str] = "turn_started"
    turn: int


@dataclass(frozen=True, slots=True)
class MessageDelta:
    type: ClassVar[str] = "message_delta"
    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    type: ClassVar[str] = "tool_started"
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCompleted:
    type: ClassVar[str] = "tool_completed"
    call_id: str
    name: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CitationAvailable:
    type: ClassVar[str] = "citation_available"
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class CitationEvent:
    type: ClassVar[str] = "citation"
    evidence_id: str
    title: str
    page: str | None = None
    uri: str | None = None


@dataclass(frozen=True, slots=True)
class TurnCompleted:
    type: ClassVar[str] = "turn_completed"
    turn: int
    outcome: Literal["tool", "final"]


@dataclass(frozen=True, slots=True)
class RunCompleted:
    type: ClassVar[str] = "run_completed"


@dataclass(frozen=True, slots=True)
class RunFailed:
    type: ClassVar[str] = "run_failed"
    error: str


AgentEvent: TypeAlias = (
    RunStarted
    | TurnStarted
    | MessageDelta
    | ToolStarted
    | ToolCompleted
    | CitationAvailable
    | CitationEvent
    | TurnCompleted
    | RunCompleted
    | RunFailed
)

__all__ = [
    "AgentContext",
    "AgentEvent",
    "CitationAvailable",
    "CitationEvent",
    "Evidence",
    "MessageDelta",
    "ModelTurn",
    "RunCompleted",
    "RunFailed",
    "RunStarted",
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
