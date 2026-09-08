"""Provider-neutral contracts for BoThesis's single-agent turn runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from bothesis.agent.models import AgentContext, CitationReferences, ConversationMessage
from bothesis.agent.protocol import Item

if TYPE_CHECKING:
    from bothesis.agent.tools import ToolRouter


class AgentExecutionError(RuntimeError):
    """The agent could not safely complete a request."""


@dataclass(frozen=True, slots=True)
class SessionConfiguration:
    """Static configuration shared by every turn in one runtime session."""

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_model_turns: int = 12
    max_tool_rounds: int = 8
    max_tool_calls: int = 6
    max_history_messages: int = 24
    max_history_characters: int = 24_000
    recent_history_messages: int = 6
    max_tool_result_characters: int = 10_000
    max_tool_context_characters: int = 12_000
    max_user_message_characters: int = 4_000
    # Wraps each tool execution, so it must stay above a tool's own budget
    # (knowledge_search allows 25s) or the executor cancels before the tool can
    # report its own timeout outcome.
    tool_timeout_seconds: float = 30.0
    max_sampling_retries: int = 2
    sampling_retry_base_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if self.max_model_turns < 1:
            raise ValueError("max_model_turns must be at least one")
        if self.max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must be non-negative")
        if self.max_tool_rounds >= self.max_model_turns:
            raise ValueError("max_tool_rounds must be lower than max_model_turns")
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least one")
        if (
            min(
                self.max_history_messages,
                self.max_history_characters,
                self.recent_history_messages,
                self.max_tool_result_characters,
                self.max_tool_context_characters,
                self.max_user_message_characters,
            )
            < 1
        ):
            raise ValueError("agent context limits must be at least one")
        if self.recent_history_messages > self.max_history_messages:
            raise ValueError("recent conversation messages exceed the history limit")
        if self.tool_timeout_seconds <= 0:
            raise ValueError("tool timeout must be greater than zero")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens must be at least one")
        if self.max_sampling_retries < 0:
            raise ValueError("max_sampling_retries must be non-negative")
        if self.sampling_retry_base_delay_seconds <= 0:
            raise ValueError("sampling_retry_base_delay_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class ConversationWindow:
    """A bounded history split into compressible and recent messages."""

    older_messages: tuple[ConversationMessage, ...]
    recent_messages: tuple[ConversationMessage, ...]

    @property
    def messages(self) -> tuple[ConversationMessage, ...]:
        return (*self.older_messages, *self.recent_messages)

    def older_payload(self) -> list[dict[str, str]]:
        return _message_payload(self.older_messages)

    def older_json(self) -> str:
        return _compact_json(self.older_payload())


@dataclass(frozen=True, slots=True)
class PreparedConversation:
    """The canonical input items and base instructions for one turn."""

    items: tuple[Item, ...]
    instructions: str


@dataclass(frozen=True, slots=True)
class SessionServices:
    """Session-scoped dependencies; these never become model context."""

    model: object
    tool_registry: object
    tracing: object | None = None


@dataclass(frozen=True, slots=True)
class ResolvedStepSettings:
    """Exact model and sampling settings used by one sampling request."""

    model: str | None
    temperature: float | None
    max_output_tokens: int | None
    parallel_tool_calls: bool
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnEnvironmentSnapshot:
    """Stable request environment captured for a sampling step."""

    agent_context: AgentContext


@dataclass(slots=True)
class TurnContext:
    """Mutable accounting and policy state for one user-initiated turn."""

    user_input: str
    environment: TurnEnvironmentSnapshot
    initial_settings: ResolvedStepSettings
    current_settings: ResolvedStepSettings
    id: str = field(default_factory=lambda: f"turn_{uuid4().hex}")
    model_iteration: int = 0
    tool_round: int = 0
    tool_call_count: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)
    used_evidence_ids: set[str] = field(default_factory=set)
    executed_tool_signatures: set[str] = field(default_factory=set)
    references: CitationReferences = field(default_factory=CitationReferences)


@dataclass(frozen=True, slots=True)
class StepContext:
    """Immutable snapshot used by exactly one model sampling request."""

    turn: TurnContext
    settings: ResolvedStepSettings
    environment: TurnEnvironmentSnapshot
    tool_router: "ToolRouter"


def duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1_000)


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _message_payload(
    messages: tuple[ConversationMessage, ...],
) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


# Import primary runtime classes only after the shared package contracts exist.
from bothesis.agent.context_manager import ContextManager  # noqa: E402
from bothesis.agent.session import Session  # noqa: E402
from bothesis.agent.agent import Agent  # noqa: E402

__all__ = [
    "Agent",
    "AgentExecutionError",
    "ConversationWindow",
    "ContextManager",
    "PreparedConversation",
    "ResolvedStepSettings",
    "Session",
    "SessionConfiguration",
    "SessionServices",
    "StepContext",
    "TurnContext",
    "TurnEnvironmentSnapshot",
    "duration_ms",
]
