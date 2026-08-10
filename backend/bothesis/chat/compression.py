"""Bound and represent conversation context before model execution."""

from __future__ import annotations

import json
from dataclasses import dataclass

from bothesis.agent.models import ConversationMessage


@dataclass(frozen=True, slots=True)
class ConversationContextPolicy:
    """Apply deterministic context limits around optional LLM compression."""

    max_messages: int
    max_characters: int
    compression_threshold: int
    max_compressed_characters: int

    def __post_init__(self) -> None:
        if (
            min(
                self.max_messages,
                self.max_characters,
                self.compression_threshold,
                self.max_compressed_characters,
            )
            < 1
        ):
            raise ValueError("conversation context limits must be at least one")

    def bounded(self, history: tuple[ConversationMessage, ...]) -> str:
        """Keep the newest non-empty messages within the configured budget."""

        remaining_characters = self.max_characters
        bounded_messages: list[dict[str, str]] = []
        for message in reversed(history[-self.max_messages :]):
            content = message.content.strip()
            if not content or remaining_characters <= 0:
                continue
            content = content[-remaining_characters:]
            bounded_messages.append({"role": message.role, "content": content})
            remaining_characters -= len(content)
        return _compact_json(list(reversed(bounded_messages)))

    def needs_compression(self, conversation: str) -> bool:
        return len(conversation) > self.compression_threshold


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = ["ConversationContextPolicy"]
