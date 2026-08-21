from __future__ import annotations

from collections.abc import Mapping

from bothesis.agent.citation import CitationRenderer
from bothesis.agent.models import Evidence
from bothesis.agent.protocol import (
    DOCUMENT_CITATION_TYPE,
    Annotation,
    MessageItem,
    OutputText,
    ResponseContentPartDoneEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseStreamEvent,
)

_PartKey = tuple[int, int]


class CitationProjection:
    """Rewrite one response stream so citations become annotations."""

    def __init__(self, evidence: Mapping[str, Evidence]) -> None:
        self._evidence = evidence
        self._renderers: dict[_PartKey, CitationRenderer] = {}
        self._text: dict[_PartKey, list[str]] = {}
        self._annotations: dict[_PartKey, list[Annotation]] = {}
        self._used_evidence_ids: set[str] = set()

    @property
    def used_evidence_ids(self) -> frozenset[str]:
        """Every evidence id the model actually cited."""

        return frozenset(self._used_evidence_ids)

    def project(self, event: ResponseStreamEvent) -> tuple[ResponseStreamEvent, ...]:
        """Return the events to forward in place of one incoming event."""

        if not self._evidence:
            return (event,)
        if isinstance(event, ResponseOutputTextDeltaEvent):
            return self._delta(event)
        if isinstance(event, ResponseOutputTextDoneEvent):
            key = (event.output_index, event.content_index)
            flushed = self._flush(event)
            return (
                *flushed,
                event.model_copy(update={"text": self._value(key)}),
            )
        if isinstance(event, ResponseContentPartDoneEvent) and isinstance(
            event.part, OutputText
        ):
            key = (event.output_index, event.content_index)
            if key not in self._text:
                return (event,)
            return (
                event.model_copy(
                    update={
                        "part": OutputText(
                            text=self._value(key),
                            annotations=self._merged(key, event.part.annotations),
                        )
                    }
                ),
            )
        if isinstance(event, ResponseOutputItemDoneEvent) and isinstance(
            event.item, MessageItem
        ):
            return (
                event.model_copy(
                    update={"item": self._message(event.output_index, event.item)}
                ),
            )
        return (event,)

    def _delta(
        self, event: ResponseOutputTextDeltaEvent
    ) -> tuple[ResponseStreamEvent, ...]:
        key = (event.output_index, event.content_index)
        renderer = self._renderers.setdefault(key, CitationRenderer())
        events: list[ResponseStreamEvent] = []
        for visible_text, evidence_id in renderer.push(
            event.delta, self._evidence, self._used_evidence_ids
        ):
            if visible_text:
                self._text.setdefault(key, []).append(visible_text)
                events.append(event.model_copy(update={"delta": visible_text}))
            if evidence_id:
                events.append(self._annotation_event(event, key, evidence_id))
        self._text.setdefault(key, [])
        return tuple(events)

    def _flush(
        self, event: ResponseOutputTextDoneEvent
    ) -> tuple[ResponseStreamEvent, ...]:
        key = (event.output_index, event.content_index)
        renderer = self._renderers.get(key)
        if renderer is None:
            return ()
        trailing = renderer.flush()
        if trailing is None or not trailing[0]:
            return ()
        self._text.setdefault(key, []).append(trailing[0])
        return (
            ResponseOutputTextDeltaEvent(
                item_id=event.item_id,
                output_index=event.output_index,
                content_index=event.content_index,
                delta=trailing[0],
            ),
        )

    def _annotation_event(
        self,
        event: ResponseOutputTextDeltaEvent,
        key: _PartKey,
        evidence_id: str,
    ) -> ResponseOutputTextAnnotationAddedEvent:
        annotations = self._annotations.setdefault(key, [])
        annotation = _document_citation(self._evidence[evidence_id], len(self._value(key)))
        annotations.append(annotation)
        return ResponseOutputTextAnnotationAddedEvent(
            item_id=event.item_id,
            output_index=event.output_index,
            content_index=event.content_index,
            annotation_index=len(annotations) - 1,
            annotation=annotation,
        )

    def _message(self, output_index: int, item: MessageItem) -> MessageItem:
        content = tuple(
            OutputText(
                text=self._value((output_index, content_index)),
                annotations=self._merged((output_index, content_index), part.annotations),
            )
            if isinstance(part, OutputText)
            and (output_index, content_index) in self._text
            else part
            for content_index, part in enumerate(item.content)
        )
        return item.model_copy(update={"content": content})

    def _merged(
        self, key: _PartKey, existing: tuple[Annotation, ...]
    ) -> tuple[Annotation, ...]:
        merged = list(existing)
        for annotation in self._annotations.get(key, ()):
            if annotation not in merged:
                merged.append(annotation)
        return tuple(merged)

    def _value(self, key: _PartKey) -> str:
        return "".join(self._text.get(key, ()))


def _document_citation(evidence: Evidence, offset: int) -> Annotation:
    """Build the one BoThesis annotation type from an evidence record."""

    return {
        "type": DOCUMENT_CITATION_TYPE,
        "start_index": offset,
        "end_index": offset,
        "citation": {
            "id": evidence.id,
            "document_id": evidence.document_id,
            "title": evidence.title,
            "page": evidence.page,
            "section": evidence.section,
            "uri": evidence.uri,
            "source": evidence.source,
        },
    }


__all__ = ["CitationProjection"]
