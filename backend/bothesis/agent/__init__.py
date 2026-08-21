"""Public contracts and runtime entry points for the BoThesis agent.

The package has one execution path: :class:`Agent` delegates to
:class:`ConversationSession`, which constructs one Turn Request per user
message to alternate dynamically between native tool calls and final
response generation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, TypeAlias

from bothesis.agent.models import ConversationMessage
from bothesis.agent.protocol import Item, Response

ModelMessage: TypeAlias = dict[str, Any]
"""One rendered provider wire message, as produced by ``TurnInput`` rendering."""

class AgentExecutionError(RuntimeError):
    """The agent could not safely complete a request."""


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Typed circuit breakers and context limits for one agent runtime."""

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
    tool_timeout_seconds: float = 8.0
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
class ModelStreamCompleted:
    """One provider stream normalized into a protocol response.

    ``items`` is the canonical, provider-neutral output of this sampling
    request (in :mod:`bothesis.agent.protocol` terms) so the next request can
    replay it verbatim through :class:`~bothesis.agent.turn_input.TurnInput`;
    ``response`` is the neutral view the runtime reasons about.
    """

    response: Response
    duration_ms: int
    items: tuple[Item, ...] = ()
    used_evidence_ids: frozenset[str] = frozenset()


def duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1_000)


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _message_payload(
    messages: tuple[ConversationMessage, ...],
) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


# Import primary runtime classes only after the shared package contracts exist.
from bothesis.agent.agent import Agent  # noqa: E402
from bothesis.agent.conversation_compression import ConversationMemory  # noqa: E402
from bothesis.agent.conversation_session import ConversationSession  # noqa: E402

__all__ = [
    "Agent",
    "AgentConfig",
    "AgentExecutionError",
    "ConversationMemory",
    "ConversationSession",
    "ConversationWindow",
    "ModelMessage",
    "ModelStreamCompleted",
    "duration_ms",
]
