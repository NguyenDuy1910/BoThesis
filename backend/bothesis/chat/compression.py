"""Bound and represent conversation context before model execution."""

from __future__ import annotations

import json
from dataclasses import dataclass

from bothesis.agent.models import ConversationMessage


@dataclass(frozen=True, slots=True)
class ConversationWindow:
    """One turn-safe history window shared by every model capability."""

    older_messages: tuple[ConversationMessage, ...]
    recent_messages: tuple[ConversationMessage, ...]

    @property
    def messages(self) -> tuple[ConversationMessage, ...]:
        return (*self.older_messages, *self.recent_messages)

    def older_json(self) -> str:
        return _compact_json(self.older_payload())

    def older_payload(self) -> list[dict[str, str]]:
        return _message_payload(self.older_messages)

    def context_json(self, *, summary: str | None = None) -> str:
        return _compact_json(self.context_payload(summary=summary))

    def context_payload(self, *, summary: str | None = None) -> dict[str, object]:
        messages = self.recent_messages if summary is not None else self.messages
        return {
            "older_summary": summary,
            "messages": _message_payload(messages),
        }


@dataclass(frozen=True, slots=True)
class ConversationContextPolicy:
    """Apply deterministic context limits around optional LLM compression."""

    max_messages: int
    max_characters: int
    compression_threshold: int
    max_compressed_characters: int
    recent_messages: int = 6

    def __post_init__(self) -> None:
        if (
            min(
                self.max_messages,
                self.max_characters,
                self.compression_threshold,
                self.max_compressed_characters,
                self.recent_messages,
            )
            < 1
        ):
            raise ValueError("conversation context limits must be at least one")
        if self.recent_messages > self.max_messages:
            raise ValueError("recent conversation messages exceed the history limit")

    def window(
        self,
        history: tuple[ConversationMessage, ...],
    ) -> ConversationWindow:
        """Keep complete recent messages without tail-only or orphaned context."""

        candidates = [
            ConversationMessage(role=message.role, content=message.content.strip())
            for message in history[-self.max_messages :]
            if message.content.strip()
        ]
        remaining_characters = self.max_characters
        selected_reversed: list[ConversationMessage] = []
        for message in reversed(candidates):
            if len(message.content) > remaining_characters:
                break
            selected_reversed.append(message)
            remaining_characters -= len(message.content)

        selected = list(reversed(selected_reversed))
        # An assistant response without its preceding user request is more
        # misleading than useful, so drop it when a budget boundary splits a turn.
        while selected and selected[0].role == "assistant":
            selected.pop(0)

        split_at = max(0, len(selected) - self.recent_messages)
        if (
            split_at > 0
            and split_at < len(selected)
            and selected[split_at].role == "assistant"
            and selected[split_at - 1].role == "user"
        ):
            split_at -= 1
        return ConversationWindow(
            older_messages=tuple(selected[:split_at]),
            recent_messages=tuple(selected[split_at:]),
        )

    def bounded(self, history: tuple[ConversationMessage, ...]) -> str:
        """Return the bounded conversation as compact JSON."""

        return _messages_json(self.window(history).messages)

    def needs_compression(self, window: ConversationWindow) -> bool:
        return bool(window.older_messages) and (
            len(window.older_json()) > self.compression_threshold
        )


def _messages_json(messages: tuple[ConversationMessage, ...]) -> str:
    return _compact_json(_message_payload(messages))


def _message_payload(
    messages: tuple[ConversationMessage, ...],
) -> list[dict[str, str]]:
    return [
        {"role": message.role, "content": message.content}
        for message in messages
    ]


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = ["ConversationContextPolicy", "ConversationWindow"]
