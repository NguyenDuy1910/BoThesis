"""The one canonical, provider-neutral conversation history for a turn.

A turn is fed by two distinct kinds of entry, exactly as in Codex's own
``TurnInput``: fresh, not-yet-canonical content a user submitted
(:class:`UserInput`) and an already-canonical protocol item being replayed
or injected directly (:class:`ResponseItem` — model commentary, tool calls,
tool results). ``TurnInput`` stores ``instructions`` (the base system prompt,
equivalent to a Prompt's ``base_instructions``) plus the ordered sequence of
entries, and renders both into each provider's own wire shape on demand.
OpenAI's Responses API takes ``instructions`` as its own top-level parameter;
OpenRouter's chat-completions API has no such parameter, so it is rendered
there as a leading system message instead. The inbound half — turning a
provider's raw stream into canonical items — lives in
:mod:`bothesis.agent.response_stream`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

from bothesis.agent.protocol import (
    ContentPart,
    FunctionCallItem,
    FunctionCallOutputItem,
    InputFile,
    InputImage,
    InputText,
    Item,
    MessageItem,
    OutputText,
    ReasoningItem,
)

_ASSISTANT_GROUP_TYPES = (ReasoningItem, FunctionCallItem)


@dataclass(frozen=True, slots=True)
class UserInput:
    """Fresh content a user submitted for this turn, not yet a canonical item."""

    content: tuple[ContentPart, ...]


@dataclass(frozen=True, slots=True)
class ResponseItem:
    """An already-canonical protocol item submitted directly into the turn."""

    item: Item


TurnInputEntry: TypeAlias = UserInput | ResponseItem


@dataclass(frozen=True, slots=True)
class TurnInput:
    """The base instructions plus an immutable, ordered sequence of entries."""

    entries: tuple[TurnInputEntry, ...] = ()
    instructions: str | None = None

    def extend(self, entries: Sequence[TurnInputEntry]) -> "TurnInput":
        return TurnInput(entries=(*self.entries, *entries), instructions=self.instructions)

    @property
    def items(self) -> tuple[Item, ...]:
        """Project every entry onto its canonical protocol item, in order."""

        return tuple(_as_item(entry) for entry in self.entries)

    def to_openai_input(self) -> list[dict[str, Any]]:
        """Render the history as OpenAI Responses API input items."""

        rendered: list[dict[str, Any]] = []
        for item in self.items:
            block = _openai_item(item)
            if block is not None:
                rendered.append(block)
        return rendered

    def to_openrouter_messages(self) -> list[dict[str, Any]]:
        """Render the history as chat-completions messages."""

        call_names = {
            item.call_id: item.name
            for item in self.items
            if isinstance(item, FunctionCallItem)
        }
        rendered: list[dict[str, Any]] = []
        if self.instructions:
            rendered.append({"role": "system", "content": self.instructions})
        pending: list[Item] = []

        def flush() -> None:
            if pending:
                rendered.append(_openrouter_assistant_message(pending))
                pending.clear()

        for item in self.items:
            if isinstance(item, _ASSISTANT_GROUP_TYPES) or (
                isinstance(item, MessageItem) and item.role == "assistant"
            ):
                pending.append(item)
                continue
            flush()
            if isinstance(item, FunctionCallOutputItem):
                rendered.append(
                    {
                        "role": "tool",
                        "name": call_names.get(item.call_id, ""),
                        "tool_call_id": item.call_id,
                        "content": item.output,
                    }
                )
            elif isinstance(item, MessageItem):
                rendered.append(_openrouter_plain_message(item))
        flush()
        return rendered


def _as_item(entry: TurnInputEntry) -> Item:
    if isinstance(entry, ResponseItem):
        return entry.item
    return MessageItem(role="user", content=entry.content)


def _openai_item(item: Item) -> dict[str, Any] | None:
    if isinstance(item, MessageItem):
        if any(
            isinstance(part, OutputText) and part.annotations for part in item.content
        ):
            # Cached OpenRouter file-caching annotations are provider-specific.
            return None
        return {"role": item.role, "content": _openai_content(item)}
    if isinstance(item, ReasoningItem):
        block: dict[str, Any] = {
            "type": "reasoning",
            "summary": [
                {"type": "summary_text", "text": part.text} for part in item.summary
            ],
        }
        if item.id is not None:
            block["id"] = item.id
        if item.encrypted_content is not None:
            block["encrypted_content"] = item.encrypted_content
        return block
    if isinstance(item, FunctionCallItem):
        block = {"type": "function_call", "call_id": item.call_id, "name": item.name, "arguments": item.arguments}
        if item.id is not None:
            block["id"] = item.id
        return block
    if isinstance(item, FunctionCallOutputItem):
        return {"type": "function_call_output", "call_id": item.call_id, "output": item.output}
    return None


def _openai_content(item: MessageItem) -> str | list[dict[str, Any]]:
    if len(item.content) == 1:
        part = item.content[0]
        if isinstance(part, (InputText, OutputText)):
            return part.text
    blocks: list[dict[str, Any]] = []
    for part in item.content:
        if isinstance(part, (InputText, OutputText)):
            blocks.append({"type": "input_text" if isinstance(part, InputText) else "output_text", "text": part.text})
        elif isinstance(part, InputImage):
            block: dict[str, Any] = {"type": "input_image", "detail": part.detail}
            if part.image_url is not None:
                block["image_url"] = part.image_url
            if part.file_id is not None:
                block["file_id"] = part.file_id
            blocks.append(block)
        elif isinstance(part, InputFile):
            block = {"type": "input_file"}
            for key in ("file_id", "file_url", "filename", "file_data"):
                value = getattr(part, key)
                if value is not None:
                    block[key] = value
            blocks.append(block)
    return blocks


def _openrouter_plain_message(item: MessageItem) -> dict[str, Any]:
    message: dict[str, Any] = {"role": item.role, "content": _openrouter_content(item)}
    for part in item.content:
        if isinstance(part, OutputText) and part.annotations:
            message["annotations"] = [dict(annotation) for annotation in part.annotations]
    return message


def _openrouter_content(item: MessageItem) -> str | list[dict[str, Any]]:
    if len(item.content) == 1:
        part = item.content[0]
        if isinstance(part, (InputText, OutputText)):
            return part.text
    blocks: list[dict[str, Any]] = []
    for part in item.content:
        if isinstance(part, (InputText, OutputText)):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, InputImage) and part.image_url is not None:
            blocks.append({"type": "image_url", "image_url": {"url": part.image_url}})
        elif isinstance(part, InputFile):
            file_block: dict[str, Any] = {}
            if part.filename is not None:
                file_block["filename"] = part.filename
            if part.file_data is not None:
                file_block["file_data"] = part.file_data
            blocks.append({"type": "file", "file": file_block})
    return blocks


def _openrouter_assistant_message(group: Sequence[Item]) -> dict[str, Any]:
    text = ""
    annotations: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    reasoning_details: list[dict[str, Any]] | None = None
    for item in group:
        if isinstance(item, ReasoningItem):
            reasoning_details = _decode_reasoning_details(item.encrypted_content)
        elif isinstance(item, MessageItem):
            text = item.text
            for part in item.content:
                if isinstance(part, OutputText):
                    annotations.extend(dict(annotation) for annotation in part.annotations)
        elif isinstance(item, FunctionCallItem):
            tool_calls.append(
                {
                    "id": item.call_id,
                    "type": "function",
                    "function": {"name": item.name, "arguments": item.arguments},
                }
            )
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if reasoning_details:
        message["reasoning_details"] = reasoning_details
    if annotations:
        message["annotations"] = annotations
    return message


def encode_reasoning_details(reasoning_details: Sequence[dict[str, Any]]) -> str:
    """Pack OpenRouter's opaque reasoning continuation blob for canonical storage."""

    return json.dumps(list(reasoning_details), ensure_ascii=False)


def _decode_reasoning_details(encrypted_content: str | None) -> list[dict[str, Any]] | None:
    if not encrypted_content:
        return None
    try:
        decoded = json.loads(encrypted_content)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, list):
        return None
    return [dict(entry) for entry in decoded if isinstance(entry, dict)]


__all__ = [
    "ResponseItem",
    "TurnInput",
    "TurnInputEntry",
    "UserInput",
    "encode_reasoning_details",
]
