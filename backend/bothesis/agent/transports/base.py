"""Provider-neutral message types and the abstract LLM transport contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Mapping, Sequence

from bothesis.agent.models import (
    ProviderReasoningDelta,
    TextDelta,
    ToolCallDelta,
    TurnDone,
)

MessageRole = Literal["system", "user", "assistant", "tool"]
MessageContent = str | Sequence[Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A message accepted by OpenAI-compatible chat APIs.

    ``content`` also accepts a list of content blocks, which allows vision
    requests without coupling the rest of the agent to a provider SDK.
    """

    role: MessageRole
    content: MessageContent | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: Sequence[Mapping[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            message["content"] = self.content
        if self.name is not None:
            message["name"] = self.name
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.tool_calls is not None:
            message["tool_calls"] = list(self.tool_calls)
        return message


class LLMTransportError(Exception):
    """Raised when a provider cannot complete a transport operation safely."""


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A completed model response, normalized across model providers."""

    id: str
    model: str
    content: str | None
    finish_reason: str | None
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BinaryResponse:
    """A provider response containing binary content.

    This stays in the common transport contract for provider adapters that
    support non-chat endpoints.
    """

    content: bytes
    content_type: str | None = None


class LLMTransport(ABC):
    """The provider boundary used by the agent loop."""

    @abstractmethod
    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        """Return one complete normalized model response."""
        raise NotImplementedError

    @abstractmethod
    async def stream_turn(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[
        ProviderReasoningDelta | TextDelta | ToolCallDelta | TurnDone
    ]:
        """Yield normalized stream events for one model turn."""
        raise NotImplementedError
