"""Project live assistant text into one generic message item lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from bothesis.agent.citation import CitationRenderer
from bothesis.agent.models import Evidence
from bothesis.agent.protocol import (
    ItemCompleted,
    ItemDelta,
    ItemStarted,
    MessageItem,
    OutputText,
    RuntimeStreamEvent,
)


class MessageEmitter:
    """Own the active assistant message and its incremental citation state."""

    def __init__(self) -> None:
        self._item_id: str | None = None
        self._active = False
        self._renderer = CitationRenderer()
        self._rendered_citations = False
        self._text_parts: list[str] = []
        self._used_evidence_ids: set[str] = set()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def used_evidence_ids(self) -> frozenset[str]:
        return frozenset(self._used_evidence_ids)

    def start(self, *, item_id: str) -> ItemStarted:
        """Start a message whose semantic phase is not known yet."""

        if self._active:
            raise RuntimeError("an assistant message is already active")
        self._item_id = item_id
        self._active = True
        self._renderer = CitationRenderer()
        self._rendered_citations = False
        self._text_parts = []
        self._used_evidence_ids = set()
        return ItemStarted(item=self._message(status="in_progress", phase=None))

    def delta(
        self,
        text: str,
        *,
        evidence: Mapping[str, Evidence],
        render_citations: bool,
    ) -> tuple[ItemDelta, ...]:
        """Transform and emit one provider delta without replaying history."""

        item_id = self._require_active_item_id()
        if not render_citations:
            self._text_parts.append(text)
            return (ItemDelta(item_id=item_id, delta=text),) if text else ()
        self._rendered_citations = True
        events: list[ItemDelta] = []
        for visible_text, _ in self._renderer.push(
            text, evidence, self._used_evidence_ids
        ):
            if not visible_text:
                continue
            self._text_parts.append(visible_text)
            events.append(ItemDelta(item_id=item_id, delta=visible_text))
        return tuple(events)

    def complete(
        self,
        *,
        phase: Literal["commentary", "final_answer"],
    ) -> tuple[RuntimeStreamEvent, ...]:
        """Flush the citation boundary and finalize the message's true phase."""

        item_id = self._require_active_item_id()
        events: list[RuntimeStreamEvent] = []
        trailing = self._renderer.flush() if self._rendered_citations else None
        if trailing is not None and trailing[0]:
            self._text_parts.append(trailing[0])
            events.append(ItemDelta(item_id=item_id, delta=trailing[0]))
        self._active = False
        events.append(ItemCompleted(item=self._message(status="completed", phase=phase)))
        return tuple(events)

    def _message(
        self,
        *,
        status: Literal["in_progress", "completed"],
        phase: Literal["commentary", "final_answer"] | None,
    ) -> MessageItem:
        return MessageItem(
            id=self._item_id,
            role="assistant",
            phase=phase,
            content=(OutputText(text="".join(self._text_parts)),),
            status=status,
        )

    def _require_active_item_id(self) -> str:
        if not self._active or self._item_id is None:
            raise RuntimeError("no assistant message is active")
        return self._item_id


__all__ = ["MessageEmitter"]
