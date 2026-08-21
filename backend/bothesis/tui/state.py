"""Reducer-backed materialized state for the semantic agent stream."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping
from uuid import UUID, uuid4


HistoryRole = Literal["user", "assistant"]
MAX_HISTORY_MESSAGES = 24
MAX_HISTORY_CHARACTERS = 24_000
MAX_HISTORY_MESSAGE_CHARACTERS = 8_000


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    role: HistoryRole
    content: str


@dataclass(slots=True)
class OutputItemState:
    id: str
    type: str
    output_index: int
    status: str | None = None
    role: str | None = None
    content: list[dict[str, Any]] = field(default_factory=list)
    call_id: str | None = None
    name: str | None = None
    arguments: str = ""

    @property
    def text(self) -> str:
        return "".join(
            _string(part.get("text"))
            for part in self.content
            if part.get("type") == "output_text"
        )


@dataclass(slots=True)
class ResponseState:
    id: str
    status: str = "in_progress"
    items: dict[str, OutputItemState] = field(default_factory=dict)
    item_order: list[str] = field(default_factory=list)

    @property
    def has_function_call(self) -> bool:
        return any(item.type == "function_call" for item in self.items.values())

    @property
    def assistant_text(self) -> str:
        return "\n\n".join(
            item.text
            for item_id in self.item_order
            if (item := self.items[item_id]).type == "message"
            and item.role == "assistant"
            and item.text
        )


@dataclass(slots=True)
class TurnState:
    responses: dict[str, ResponseState] = field(default_factory=dict)
    response_order: list[str] = field(default_factory=list)
    status: str = "in_progress"
    error: str | None = None
    last_sequence_number: int = -1

    @property
    def stream_text(self) -> str:
        return "\n\n".join(
            response.assistant_text
            for response_id in self.response_order
            if (response := self.responses[response_id]).assistant_text
        )

    @property
    def final_text(self) -> str:
        """The final no-tool assistant message suitable for next-turn history."""

        for response_id in reversed(self.response_order):
            response = self.responses[response_id]
            if response.status == "completed" and not response.has_function_call:
                if response.assistant_text:
                    return response.assistant_text
        return ""

    @property
    def function_calls(self) -> tuple[OutputItemState, ...]:
        return tuple(
            item
            for response_id in self.response_order
            for item_id in self.responses[response_id].item_order
            if (item := self.responses[response_id].items[item_id]).type == "function_call"
        )


@dataclass(slots=True)
class ChatState:
    """A deterministic reducer for public response lifecycle events."""

    conversation_id: str = field(default_factory=lambda: str(uuid4()))
    history: list[HistoryMessage] = field(default_factory=list)
    turn: TurnState | None = None
    raw_sse_lines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        try:
            UUID(self.conversation_id)
        except ValueError as exc:
            raise ValueError("conversation_id must be a UUID") from exc

    def begin_turn(self, message: str) -> TurnState:
        self.history.append(HistoryMessage(role="user", content=message))
        self.turn = TurnState()
        return self.turn

    def request_history(self) -> list[HistoryMessage]:
        remaining_characters = MAX_HISTORY_CHARACTERS
        selected: list[HistoryMessage] = []
        for entry in reversed(self.history):
            content = _clip_history(entry.content)
            if not content:
                continue
            if len(selected) == MAX_HISTORY_MESSAGES or len(content) > remaining_characters:
                break
            selected.append(HistoryMessage(role=entry.role, content=content))
            remaining_characters -= len(content)
        selected.reverse()
        while selected and selected[0].role == "assistant":
            selected.pop(0)
        return selected

    def apply_event(self, event: Mapping[str, Any], *, raw_sse_line: str) -> TurnState:
        if self.turn is None:
            self.turn = TurnState()
        sequence_number = _integer(event.get("sequence_number"))
        if sequence_number is None or sequence_number <= self.turn.last_sequence_number:
            return self.turn
        self.turn.last_sequence_number = sequence_number
        self.raw_sse_lines.append(raw_sse_line)

        event_type = _string(event.get("type"))
        if event_type == "response.created":
            response = event.get("response")
            if isinstance(response, Mapping):
                response_id = _string(event.get("response_id")) or _string(response.get("id"))
                if response_id:
                    self._response(response_id).status = _string(response.get("status")) or "in_progress"
        elif event_type == "response.output_item.added":
            response = self._response_from_event(event)
            item = event.get("item")
            if response is not None and isinstance(item, Mapping):
                self._upsert_item(response, item, _integer(event.get("output_index")) or 0)
        elif event_type == "response.content_part.added":
            item = self._item_from_event(event)
            part = event.get("part")
            if item is not None and isinstance(part, Mapping):
                self._set_part(item, _integer(event.get("content_index")) or 0, part)
        elif event_type == "response.output_text.delta":
            item = self._item_from_event(event)
            if item is not None:
                part = self._part(item, _integer(event.get("content_index")) or 0)
                part["type"] = "output_text"
                part["text"] = _string(part.get("text")) + _string(event.get("delta"))
        elif event_type == "response.output_text.done":
            item = self._item_from_event(event)
            if item is not None:
                part = self._part(item, _integer(event.get("content_index")) or 0)
                part["type"] = "output_text"
                part["text"] = _string(event.get("text"))
        elif event_type == "response.output_text.annotation.added":
            item = self._item_from_event(event)
            annotation = event.get("annotation")
            if item is not None and isinstance(annotation, Mapping):
                part = self._part(item, _integer(event.get("content_index")) or 0)
                annotations = part.setdefault("annotations", [])
                if isinstance(annotations, list):
                    annotations.append(dict(annotation))
        elif event_type == "response.function_call_arguments.delta":
            item = self._item_from_event(event)
            if item is not None:
                item.arguments += _string(event.get("delta"))
        elif event_type == "response.function_call_arguments.done":
            item = self._item_from_event(event)
            if item is not None:
                item.arguments = _string(event.get("arguments"))
        elif event_type == "response.output_item.done":
            response = self._response_from_event(event)
            item = event.get("item")
            if response is not None and isinstance(item, Mapping):
                projected = self._upsert_item(response, item, _integer(event.get("output_index")) or 0)
                projected.status = _string(item.get("status")) or "completed"
        elif event_type in {"response.completed", "response.incomplete", "response.failed"}:
            response = event.get("response")
            if isinstance(response, Mapping):
                response_id = _string(response.get("id"))
                if response_id:
                    materialized = self._response(response_id)
                    materialized.status = _string(response.get("status")) or event_type.removeprefix("response.")
                    if event_type == "response.failed":
                        self.turn.status = "failed"
                        error = response.get("error")
                        self.turn.error = _string(error.get("message")) if isinstance(error, Mapping) else "Model response failed."
                    elif event_type == "response.incomplete":
                        self.turn.status = "incomplete"
                    elif materialized.assistant_text and not materialized.has_function_call:
                        self.turn.status = "completed"
        return self.turn

    def complete_turn(self) -> None:
        if self.turn is None or self.turn.status != "completed":
            return
        answer = self.turn.final_text.strip()
        if answer:
            self.history.append(HistoryMessage(role="assistant", content=answer))

    def reset(self) -> None:
        self.conversation_id = str(uuid4())
        self.history.clear()
        self.turn = None
        self.raw_sse_lines.clear()

    def _response(self, response_id: str) -> ResponseState:
        response = self.turn.responses.get(response_id)
        if response is None:
            response = ResponseState(id=response_id)
            self.turn.responses[response_id] = response
            self.turn.response_order.append(response_id)
        return response

    def _response_from_event(self, event: Mapping[str, Any]) -> ResponseState | None:
        response_id = _string(event.get("response_id"))
        return self._response(response_id) if response_id else None

    def _item_from_event(self, event: Mapping[str, Any]) -> OutputItemState | None:
        response = self._response_from_event(event)
        item_id = _string(event.get("item_id"))
        if response is None or not item_id:
            return None
        item = response.items.get(item_id)
        if item is None:
            item = OutputItemState(id=item_id, type="message", output_index=_integer(event.get("output_index")) or 0)
            response.items[item_id] = item
            response.item_order.append(item_id)
        return item

    def _upsert_item(
        self, response: ResponseState, payload: Mapping[str, Any], output_index: int
    ) -> OutputItemState:
        item_id = _string(payload.get("id")) or f"{response.id}:output:{output_index}"
        item = response.items.get(item_id)
        if item is None:
            item = OutputItemState(id=item_id, type=_string(payload.get("type")), output_index=output_index)
            response.items[item_id] = item
            response.item_order.append(item_id)
        item.type = _string(payload.get("type")) or item.type
        item.status = _string(payload.get("status")) or item.status
        item.role = _string(payload.get("role")) or item.role
        item.call_id = _string(payload.get("call_id")) or item.call_id
        item.name = _string(payload.get("name")) or item.name
        if "arguments" in payload:
            item.arguments = _string(payload.get("arguments"))
        content = payload.get("content")
        if isinstance(content, list):
            item.content = [dict(part) for part in content if isinstance(part, Mapping)]
        return item

    @staticmethod
    def _set_part(item: OutputItemState, index: int, part: Mapping[str, Any]) -> None:
        while len(item.content) <= index:
            item.content.append({})
        item.content[index] = dict(part)

    @staticmethod
    def _part(item: OutputItemState, index: int) -> dict[str, Any]:
        while len(item.content) <= index:
            item.content.append({})
        return item.content[index]


def _clip_history(content: str) -> str:
    if len(content) <= MAX_HISTORY_MESSAGE_CHARACTERS:
        return content
    marker = "\n…\n"
    available = MAX_HISTORY_MESSAGE_CHARACTERS - len(marker)
    leading = (available + 1) // 2
    return f"{content[:leading]}{marker}{content[-(available - leading):]}"


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


__all__ = [
    "ChatState",
    "HistoryMessage",
    "OutputItemState",
    "ResponseState",
    "TurnState",
]
