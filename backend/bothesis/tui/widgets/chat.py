"""Textual widgets that render terminal chat state."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, RichLog, Static

from bothesis.tui.state import OutputItemState, TurnState


class UserMessage(Vertical):
    """A compact user message block."""

    def __init__(self, message: str) -> None:
        super().__init__(classes="user-message")
        self._message = message

    def compose(self) -> ComposeResult:
        yield Static("You", classes="chat-label")
        yield Markdown(self._message, classes="user-markdown")


class AssistantTurn(Vertical):
    """Render materialized response items without agent-loop concepts."""

    def __init__(self, turn: TurnState) -> None:
        super().__init__(classes="assistant-turn")
        self._turn = turn
        self._last_answer = ""
        self._last_activity = ""

    def compose(self) -> ComposeResult:
        yield Static("Assistant", classes="chat-label")
        yield Static("", classes="activity")
        yield Markdown("", classes="assistant-markdown")
        yield Static("", classes="turn-error")

    async def render_turn(self, turn: TurnState) -> None:
        """Update only the visible projection; stream handling stays in state."""

        self._turn = turn
        answer = turn.stream_text
        activity = _activity_text(turn)
        answer_widget = self.query_one(".assistant-markdown", Markdown)
        activity_widget = self.query_one(".activity", Static)
        error_widget = self.query_one(".turn-error", Static)
        if answer != self._last_answer:
            self._last_answer = answer
            answer_widget.update(answer)
        if activity != self._last_activity:
            self._last_activity = activity
            activity_widget.update(Text(activity, style="dim"))
        answer_widget.display = bool(answer)
        activity_widget.display = bool(activity)
        error_widget.update(Text(turn.error or "", style="bold red"))
        error_widget.display = bool(turn.error)


class RawEventLog(RichLog):
    """A receive-order log of raw API SSE data lines."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            highlight=False,
            markup=False,
            wrap=True,
            classes="raw-events",
            **kwargs,
        )

    def replace_lines(self, lines: list[str]) -> None:
        self.clear()
        for line in lines:
            self.write(Text(line, style="dim"))

    def append_line(self, line: str) -> None:
        self.write(Text(line, style="dim"))


def _activity_text(turn: TurnState) -> str:
    return "\n".join(_format_activity(call) for call in turn.function_calls)


def _format_activity(call: OutputItemState) -> str:
    marker = "◌" if call.status == "in_progress" else "✓"
    name = (call.name or "tool").replace("_", " ").replace("-", " ").title()
    return f"  {marker} {name}"


__all__ = ["AssistantTurn", "RawEventLog", "UserMessage"]
