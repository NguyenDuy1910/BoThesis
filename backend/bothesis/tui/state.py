"""Small UI-facing projection of the public chat stream."""

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
class MessageState:
    id: str
    text: str = ""
    phase: str | None = None
    status: str | None = None


@dataclass(slots=True)
class ActivityState:
    id: str
    call_id: str
    name: str
    label: str
    category: str
    status: str = "in_progress"
    error: str | None = None
    duration_ms: int | None = None
    result_count: int | None = None


@dataclass(slots=True)
class TurnState:
    messages: dict[str, MessageState] = field(default_factory=dict)
    message_order: list[str] = field(default_factory=list)
    activities: dict[str, ActivityState] = field(default_factory=dict)
    activity_order: list[str] = field(default_factory=list)
    status: str = "in_progress"
    error: str | None = None

    def message_text(self, *, phase: str | None) -> str:
        return "\n\n".join(
            message.text
            for item_id in self.message_order
            if (message := self.messages[item_id]).phase == phase and message.text
        )

    @property
    def pending_text(self) -> str:
        return self.message_text(phase=None)

    @property
    def commentary_text(self) -> str:
        return self.message_text(phase="commentary")

    @property
    def final_text(self) -> str:
        final = self.message_text(phase="final_answer")
        if final:
            return final
        if self.status == "completed":
            return self.pending_text
        return ""


@dataclass(slots=True)
class ChatState:
    """Conversation and current-turn state consumed by the Textual widgets."""

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
        """Return a request-safe window matching the chat endpoint limits."""

        remaining_characters = MAX_HISTORY_CHARACTERS
        selected: list[HistoryMessage] = []
        for entry in reversed(self.history):
            content = _clip_history(entry.content)
            if not content:
                continue
            if (
                len(selected) == MAX_HISTORY_MESSAGES
                or len(content) > remaining_characters
            ):
                break
            selected.append(HistoryMessage(role=entry.role, content=content))
            remaining_characters -= len(content)
        selected.reverse()
        while selected and selected[0].role == "assistant":
            selected.pop(0)
        return selected

    def apply_event(self, event: Mapping[str, Any], *, raw_sse_line: str) -> TurnState:
        """Apply one public runtime event without interpreting agent internals."""

        if self.turn is None:
            self.turn = TurnState()
        self.raw_sse_lines.append(raw_sse_line)
        event_type = event.get("type")
        if event_type == "turn.started":
            self.turn.status = "in_progress"
        elif event_type == "turn.completed":
            self.turn.status = "completed"
        elif event_type == "error":
            self.turn.status = "failed"
            self.turn.error = _string(event.get("message")) or "The backend reported an error."
        elif event_type == "item.delta":
            item_id = _string(event.get("item_id"))
            if item_id:
                message = self._message(item_id)
                message.text += _string(event.get("delta"))
        elif event_type in {"item.started", "item.completed"}:
            item = event.get("item")
            if isinstance(item, Mapping):
                self._apply_item(item, completed=event_type == "item.completed")
        return self.turn

    def complete_turn(self) -> None:
        """Add the answer, excluding commentary, to next-turn API history."""

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

    def _apply_item(self, item: Mapping[str, Any], *, completed: bool) -> None:
        item_type = item.get("type")
        if item_type == "message":
            item_id = _string(item.get("id"))
            if not item_id:
                return
            message = self._message(item_id)
            completed_text = _content_text(item.get("content"))
            if completed_text:
                message.text = completed_text
            message.phase = _string(item.get("phase")) or message.phase
            message.status = _string(item.get("status")) or (
                "completed" if completed else message.status
            )
        elif item_type == "tool_call":
            item_id = _string(item.get("id"))
            call_id = _string(item.get("call_id"))
            name = _string(item.get("name"))
            if not item_id or not call_id or not name:
                return
            activity = self._activity(item_id, call_id, name, item)
            activity.status = _string(item.get("status")) or (
                "completed" if completed else activity.status
            )
        elif item_type == "tool_result":
            call_id = _string(item.get("call_id"))
            if not call_id:
                return
            activity = next(
                (candidate for candidate in self.turn.activities.values() if candidate.call_id == call_id),
                None,
            )
            if activity is None:
                return
            activity.status = _string(item.get("status")) or activity.status
            activity.error = _string(item.get("error")) or None
            activity.duration_ms = _integer(item.get("duration_ms"))
            activity.result_count = _integer(item.get("result_count"))

    def _message(self, item_id: str) -> MessageState:
        message = self.turn.messages.get(item_id)
        if message is None:
            message = MessageState(id=item_id)
            self.turn.messages[item_id] = message
            self.turn.message_order.append(item_id)
        return message

    def _activity(
        self,
        item_id: str,
        call_id: str,
        name: str,
        item: Mapping[str, Any],
    ) -> ActivityState:
        activity = self.turn.activities.get(item_id)
        if activity is None:
            activity = ActivityState(
                id=item_id,
                call_id=call_id,
                name=name,
                label=_string(item.get("label")) or _display_tool_name(name),
                category=_string(item.get("category")) or "tool",
            )
            self.turn.activities[item_id] = activity
            self.turn.activity_order.append(item_id)
        return activity


def _content_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return "".join(
        _string(part.get("text"))
        for part in value
        if isinstance(part, Mapping) and part.get("type") in {"input_text", "output_text"}
    )


def _display_tool_name(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").title()


def _clip_history(content: str) -> str:
    if len(content) <= MAX_HISTORY_MESSAGE_CHARACTERS:
        return content
    marker = "\n…\n"
    available = MAX_HISTORY_MESSAGE_CHARACTERS - len(marker)
    leading = (available + 1) // 2
    return f"{content[:leading]}{marker}{content[-(available - leading):]}"


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


__all__ = [
    "ActivityState",
    "ChatState",
    "HistoryMessage",
    "MAX_HISTORY_CHARACTERS",
    "MAX_HISTORY_MESSAGE_CHARACTERS",
    "MAX_HISTORY_MESSAGES",
    "MessageState",
    "TurnState",
]
