"""Attach the artifacts a turn produced to the assistant's answer text."""

from __future__ import annotations

from collections.abc import Mapping

from bothesis.agent.models import ConversationArtifact
from bothesis.agent.protocol import (
    ARTIFACT_ANNOTATION_TYPE,
    Annotation,
    MessageItem,
    OutputText,
    ResponseContentPartDoneEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDoneEvent,
    ResponseStreamEvent,
)

_PartKey = tuple[int, int]


class ArtifactProjection:
    """Rewrite one response stream so produced artifacts become annotations.

    This mirrors how a provider attaches a sandbox-generated file to the
    message that presents it: each artifact created or revised so far in the
    turn becomes one zero-width ``bothesis:artifact`` annotation at the end of
    the first text part of the response. The annotation is emitted when that
    part's text settles and merged into the settled part and item, so a client
    reading only the snapshot sees what a client following the deltas did.

    It sits after :class:`~bothesis.agent.citation_stream.CitationProjection`
    and therefore observes the citation annotations already added to a part,
    which keeps ``annotation_index`` contiguous.
    """

    def __init__(self, artifacts: Mapping[str, ConversationArtifact]) -> None:
        self._artifacts = artifacts
        self._annotation_counts: dict[_PartKey, int] = {}
        self._annotations: dict[_PartKey, tuple[Annotation, ...]] = {}
        self._annotated_part: _PartKey | None = None

    def project(self, event: ResponseStreamEvent) -> tuple[ResponseStreamEvent, ...]:
        """Return the events to forward in place of one incoming event."""

        if not self._artifacts:
            return (event,)
        if isinstance(event, ResponseOutputTextAnnotationAddedEvent):
            key = (event.output_index, event.content_index)
            self._annotation_counts[key] = max(
                self._annotation_counts.get(key, 0), event.annotation_index + 1
            )
            return (event,)
        if isinstance(event, ResponseOutputTextDoneEvent):
            key = (event.output_index, event.content_index)
            annotations = self._settle(key, len(event.text))
            if not annotations:
                return (event,)
            base = self._annotation_counts.get(key, 0)
            return (
                event,
                *(
                    ResponseOutputTextAnnotationAddedEvent(
                        item_id=event.item_id,
                        output_index=event.output_index,
                        content_index=event.content_index,
                        annotation_index=base + position,
                        annotation=annotation,
                    )
                    for position, annotation in enumerate(annotations)
                ),
            )
        if isinstance(event, ResponseContentPartDoneEvent) and isinstance(
            event.part, OutputText
        ):
            key = (event.output_index, event.content_index)
            annotations = self._settle(key, len(event.part.text))
            if not annotations:
                return (event,)
            return (
                event.model_copy(
                    update={
                        "part": OutputText(
                            text=event.part.text,
                            annotations=_merged(event.part.annotations, annotations),
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

    def _settle(self, key: _PartKey, text_length: int) -> tuple[Annotation, ...]:
        """The annotations for one part, created on the first settling event."""

        existing = self._annotations.get(key)
        if existing is not None:
            return existing
        if self._annotated_part is not None:
            return ()
        self._annotated_part = key
        annotations = tuple(
            _artifact_annotation(artifact, position=text_length)
            for artifact in self._artifacts.values()
        )
        self._annotations[key] = annotations
        return annotations

    def _message(self, output_index: int, item: MessageItem) -> MessageItem:
        content = []
        for content_index, part in enumerate(item.content):
            key = (output_index, content_index)
            annotations = (
                self._settle(key, len(part.text)) if isinstance(part, OutputText) else ()
            )
            if isinstance(part, OutputText) and annotations:
                content.append(
                    OutputText(
                        text=part.text,
                        annotations=_merged(part.annotations, annotations),
                    )
                )
            else:
                content.append(part)
        return item.model_copy(update={"content": tuple(content)})


def _merged(
    existing: tuple[Annotation, ...], added: tuple[Annotation, ...]
) -> tuple[Annotation, ...]:
    merged = list(existing)
    for annotation in added:
        if annotation not in merged:
            merged.append(annotation)
    return tuple(merged)


def _artifact_annotation(artifact: ConversationArtifact, *, position: int) -> Annotation:
    return {
        "type": ARTIFACT_ANNOTATION_TYPE,
        "start_index": position,
        "end_index": position,
        "artifact": artifact.annotation_payload(),
    }


__all__ = ["ArtifactProjection"]
