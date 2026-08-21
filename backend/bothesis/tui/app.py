"""Textual application for testing the BoThesis chat API from a terminal."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Static, TextArea

from bothesis.tui.client import BothesisChatClient, ChatClientConfig, ChatClientError
from bothesis.tui.state import ChatState
from bothesis.tui.widgets import AssistantTurn, RawEventLog, UserMessage

DEFAULT_DEVELOPMENT_USER_ID = "00000000-0000-0000-0000-000000000002"


class BothesisTui(App[None]):
    """A thin, streaming terminal view over the existing BoThesis API."""

    TITLE = "BoThesis"
    SUB_TITLE = "Enterprise knowledge chat"
    CSS = """
    Screen {
        layout: vertical;
    }

    #raw-events {
        height: 10;
        margin: 0 2;
        border: round $secondary;
        display: none;
    }

    #transcript {
        height: 1fr;
        padding: 1 2;
    }

    .chat-label {
        color: $accent;
        text-style: bold;
        margin-top: 1;
    }

    .user-markdown {
        color: $text;
    }

    .commentary {
        color: $text-muted;
    }

    .activity {
        margin: 1 0;
        color: $text-muted;
    }

    .assistant-markdown {
        color: $text;
    }

    .turn-error {
        margin-top: 1;
    }

    #composer {
        height: 5;
        margin: 0 2 1 2;
        border: round $primary;
    }

    #hint {
        color: $text-muted;
        margin: 0 2;
    }
    """
    BINDINGS = [
        Binding("ctrl+enter", "send", "Send", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
    ]

    def __init__(
        self,
        config: ChatClientConfig,
        *,
        conversation_id: str | None = None,
        raw_mode: bool = False,
    ) -> None:
        super().__init__()
        self._client = BothesisChatClient(config)
        self._state = ChatState(conversation_id=conversation_id) if conversation_id else ChatState()
        self._raw_mode = raw_mode
        self._streaming = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield RawEventLog(id="raw-events")
        with VerticalScroll(id="transcript"):
            yield Static(
                "Send a message with Ctrl+Enter. Commands: /clear, /raw, /exit.",
                id="hint",
            )
        yield TextArea(id="composer", soft_wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#composer", TextArea).focus()
        self.query_one("#raw-events", RawEventLog).display = self._raw_mode

    def action_send(self) -> None:
        if self._streaming:
            self.notify("A response is already streaming.", severity="warning")
            return
        text = self.query_one("#composer", TextArea).text.strip()
        if not text:
            return
        if text.startswith("/") and "\n" not in text:
            self._run_command(text)
            return
        self.query_one("#composer", TextArea).load_text("")
        self._streaming = True
        self._stream_message(text)

    def action_clear_chat(self) -> None:
        if self._streaming:
            self.notify("Wait for the current response before clearing.", severity="warning")
            return
        self._clear_chat()

    def _run_command(self, command: str) -> None:
        composer = self.query_one("#composer", TextArea)
        if command in {"/exit", "/quit"}:
            self.exit()
            return
        if command == "/clear":
            composer.load_text("")
            self.action_clear_chat()
            return
        if command == "/raw":
            composer.load_text("")
            self._raw_mode = not self._raw_mode
            raw_log = self.query_one("#raw-events", RawEventLog)
            raw_log.display = self._raw_mode
            if self._raw_mode:
                raw_log.replace_lines(self._state.raw_sse_lines)
            self.notify(f"Raw stream mode {'enabled' if self._raw_mode else 'disabled'}.")
            return
        self.notify(f"Unknown command: {command}", severity="warning")

    @work(exclusive=True)
    async def _stream_message(self, message: str) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        history = [
            {"role": entry.role, "content": entry.content}
            for entry in self._state.request_history()
        ]
        turn = self._state.begin_turn(message)
        await transcript.mount(UserMessage(message))
        assistant = AssistantTurn(turn)
        await transcript.mount(assistant)
        await assistant.render_turn(turn)
        transcript.scroll_end(animate=False)
        try:
            async for received in self._client.stream_turn(
                message=message,
                conversation_id=self._state.conversation_id,
                history=history,
            ):
                turn = self._state.apply_event(
                    received.event,
                    raw_sse_line=received.raw_sse_line,
                )
                if self._raw_mode:
                    self.query_one("#raw-events", RawEventLog).append_line(
                        received.raw_sse_line
                    )
                await assistant.render_turn(turn)
                transcript.scroll_end(animate=False)
            self._state.complete_turn()
        except ChatClientError as error:
            turn.error = str(error)
            turn.status = "failed"
            await assistant.render_turn(turn)
        except Exception as error:  # UI must expose transport failures, not hide them.
            turn.error = f"Unexpected client error: {error}"
            turn.status = "failed"
            await assistant.render_turn(turn)
        finally:
            self._streaming = False
            self.query_one("#composer", TextArea).focus()
            transcript.scroll_end(animate=False)

    @work(exclusive=True)
    async def _clear_chat(self) -> None:
        transcript = self.query_one("#transcript", VerticalScroll)
        for child in list(transcript.children):
            await child.remove()
        self._state.reset()
        self.query_one("#raw-events", RawEventLog).clear()
        await transcript.mount(
            Static(
                "Conversation cleared. Send a message with Ctrl+Enter.",
                id="hint",
            )
        )
        transcript.scroll_home(animate=False)


def run_tui(argv: Sequence[str] | None = None) -> None:
    """Parse terminal configuration and run the Textual client."""

    parser = argparse.ArgumentParser(description="BoThesis terminal chat client")
    parser.add_argument(
        "--api-url",
        default=os.getenv("BOTHESIS_API_URL", "http://127.0.0.1:8000"),
        help="BoThesis API base URL (default: BOTHESIS_API_URL or localhost)",
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("BOTHESIS_USER_ID") or DEFAULT_DEVELOPMENT_USER_ID,
        help=(
            "Development user UUID (default: the local streaming-test user; "
            "override with BOTHESIS_USER_ID)"
        ),
    )
    parser.add_argument(
        "--tenant-id",
        default=os.getenv("BOTHESIS_TENANT_ID"),
        help="Development tenant UUID (also read from BOTHESIS_TENANT_ID)",
    )
    parser.add_argument(
        "--access-token",
        default=os.getenv("BOTHESIS_ACCESS_TOKEN"),
        help="Optional bearer token for an authenticated API deployment",
    )
    parser.add_argument(
        "--conversation-id",
        help="Existing conversation UUID to continue",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Start with receive-order raw SSE event logging enabled",
    )
    args = parser.parse_args(argv)
    try:
        app = BothesisTui(
            ChatClientConfig(
                api_url=args.api_url,
                user_id=args.user_id,
                tenant_id=args.tenant_id,
                access_token=args.access_token,
            ),
            conversation_id=args.conversation_id,
            raw_mode=args.raw,
        )
    except ValueError as error:
        parser.error(str(error))
    app.run()


__all__ = ["BothesisTui", "run_tui"]
