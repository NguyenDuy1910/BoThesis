"""Textual widgets that render terminal chat state."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, RichLog, Static

from bothesis.tui.state import ActivityState, TurnState


class UserMessage(Vertical):
    """A compact user message block."""

    def __init__(self, message: str) -> None:
        super().__init__(classes="user-message")
        self._message = message

    def compose(self) -> ComposeResult:
        yield Static("You", classes="chat-label")
        yield Markdown(self._message, classes="user-markdown")


class AssistantTurn(Vertical):
    """Render commentary, activity, and answer from one projected turn."""

    def __init__(self, turn: TurnState) -> None:
        super().__init__(classes="assistant-turn")
        self._turn = turn
        self._last_commentary = ""
        self._last_answer = ""
        self._last_activity = ""

    def compose(self) -> ComposeResult:
        yield Static("Assistant", classes="chat-label")
        yield Markdown("", classes="commentary")
        yield Static("", classes="activity")
        yield Markdown("", classes="assistant-markdown")
        yield Static("", classes="turn-error")

    async def render_turn(self, turn: TurnState) -> None:
        """Update only the visible projection; stream handling stays in state."""

        self._turn = turn
        commentary = turn.commentary_text
        if turn.pending_text:
            commentary = "\n\n".join(part for part in (commentary, turn.pending_text) if part)
        answer = turn.final_text
        activity = _activity_text(turn)
        commentary_widget = self.query_one(".commentary", Markdown)
        answer_widget = self.query_one(".assistant-markdown", Markdown)
        activity_widget = self.query_one(".activity", Static)
        error_widget = self.query_one(".turn-error", Static)
        if commentary != self._last_commentary:
            self._last_commentary = commentary
            commentary_widget.update(commentary)
        if answer != self._last_answer:
            self._last_answer = answer
            answer_widget.update(answer)
        if activity != self._last_activity:
            self._last_activity = activity
            activity_widget.update(Text(activity, style="dim"))
        commentary_widget.display = bool(commentary)
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
    return "\n".join(_format_activity(turn.activities[item_id]) for item_id in turn.activity_order)


def _format_activity(activity: ActivityState) -> str:
    marker = {
        "in_progress": "◌",
        "completed": "✓",
        "skipped": "–",
        "failed": "×",
        "timeout": "×",
    }.get(activity.status, "•")
    details: list[str] = []
    if activity.result_count is not None:
        noun = "result" if activity.result_count == 1 else "results"
        details.append(f"{activity.result_count} {noun}")
    if activity.duration_ms is not None:
        details.append(f"{activity.duration_ms} ms")
    if activity.error:
        details.append(activity.error)
    suffix = f" — {', '.join(details)}" if details else ""
    return f"  {marker} {activity.label}{suffix}"


__all__ = ["AssistantTurn", "RawEventLog", "UserMessage"]
