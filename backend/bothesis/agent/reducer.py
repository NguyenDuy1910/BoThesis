from __future__ import annotations

from bothesis.agent.protocol import (
    ContentPart,
    ErrorEvent,
    FunctionCallItem,
    Item,
    MessageItem,
    OutputText,
    ReasoningItem,
    ReasoningText,
    Refusal,
    Response,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseError,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseInProgressEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseQueuedEvent,
    ResponseReasoningDeltaEvent,
    ResponseReasoningDoneEvent,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryPartDoneEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    ResponseRefusalDeltaEvent,
    ResponseRefusalDoneEvent,
    ResponseSnapshotEventBase,
    ResponseStreamEvent,
    SummaryText,
)
from bothesis.agent.protocol.content import Annotation

_TERMINAL_STATUS = {
    "response.completed": "completed",
    "response.incomplete": "incomplete",
    "response.failed": "failed",
}


class ResponseReducer:
    """Accumulate one response from the events that mutate it."""

    def __init__(self) -> None:
        self._envelope: Response | None = None
        self._shells: dict[int, Item] = {}
        self._items: dict[int, Item] = {}
        self._parts: dict[tuple[int, int], ContentPart] = {}
        self._text: dict[tuple[int, int], list[str]] = {}
        self._annotations: dict[tuple[int, int], list[Annotation]] = {}
        self._summary_parts: dict[tuple[int, int], ContentPart] = {}
        self._summary_text: dict[tuple[int, int], list[str]] = {}
        self._arguments: dict[int, list[str]] = {}
        self._item_ids: dict[str, int] = {}

    @property
    def response(self) -> Response | None:
        """The response as currently reconstructed, or ``None`` before it opens."""

        if self._envelope is None:
            return None
        return self._envelope.model_copy(update={"output": self.output})

    @property
    def output(self) -> tuple[Item, ...]:
        """Every reconstructed output item, in output-index order."""

        return tuple(item for _, item in sorted(self._items.items()))

    def output_index_of(self, item_id: str) -> int | None:
        """Resolve the output index an item id was first observed at."""

        return self._item_ids.get(item_id)

    def apply(self, event: ResponseStreamEvent) -> ResponseStreamEvent:
        """Fold one event into the response and return the event to forward."""

        if isinstance(
            event, (ResponseCreatedEvent, ResponseQueuedEvent, ResponseInProgressEvent)
        ):
            self._open(event.response)
            return event
        if isinstance(
            event,
            (ResponseCompletedEvent, ResponseIncompleteEvent, ResponseFailedEvent),
        ):
            return event.model_copy(update={"response": self._settle(event)})
        if isinstance(event, ErrorEvent):
            self._fail(event.error.code or "stream_error", event.error.message)
            return event
        if isinstance(event, (ResponseOutputItemAddedEvent, ResponseOutputItemDoneEvent)):
            self._place_item(
                event.output_index,
                event.item,
                done=isinstance(event, ResponseOutputItemDoneEvent),
            )
            return event
        if isinstance(
            event, (ResponseContentPartAddedEvent, ResponseContentPartDoneEvent)
        ):
            self._place_part(event.output_index, event.content_index, event.part)
        elif isinstance(event, ResponseOutputTextDeltaEvent):
            self._append_text(
                event.output_index, event.content_index, event.delta, OutputText(text="")
            )
        elif isinstance(event, ResponseOutputTextDoneEvent):
            self._set_text(
                event.output_index, event.content_index, event.text, OutputText(text="")
            )
        elif isinstance(event, ResponseOutputTextAnnotationAddedEvent):
            self._add_annotation(
                event.output_index,
                event.content_index,
                event.annotation_index,
                event.annotation,
            )
        elif isinstance(event, ResponseRefusalDeltaEvent):
            self._append_text(
                event.output_index, event.content_index, event.delta, Refusal(refusal="")
            )
        elif isinstance(event, ResponseRefusalDoneEvent):
            self._set_text(
                event.output_index,
                event.content_index,
                event.refusal,
                Refusal(refusal=""),
            )
        elif isinstance(event, ResponseReasoningDeltaEvent):
            self._append_text(
                event.output_index,
                event.content_index,
                event.delta,
                ReasoningText(text=""),
            )
        elif isinstance(event, ResponseReasoningDoneEvent):
            self._set_text(
                event.output_index,
                event.content_index,
                event.text,
                ReasoningText(text=""),
            )
        elif isinstance(
            event,
            (
                ResponseReasoningSummaryPartAddedEvent,
                ResponseReasoningSummaryPartDoneEvent,
            ),
        ):
            self._place_summary_part(
                event.output_index, event.summary_index, event.part
            )
        elif isinstance(event, ResponseReasoningSummaryTextDeltaEvent):
            self._summary_parts.setdefault(
                (event.output_index, event.summary_index), SummaryText(text="")
            )
            self._summary_text.setdefault(
                (event.output_index, event.summary_index), []
            ).append(event.delta)
        elif isinstance(event, ResponseReasoningSummaryTextDoneEvent):
            self._summary_parts.setdefault(
                (event.output_index, event.summary_index), SummaryText(text="")
            )
            self._summary_text[(event.output_index, event.summary_index)] = [event.text]
        elif isinstance(event, ResponseFunctionCallArgumentsDeltaEvent):
            self._arguments.setdefault(event.output_index, []).append(event.delta)
        elif isinstance(event, ResponseFunctionCallArgumentsDoneEvent):
            self._arguments[event.output_index] = [event.arguments]
        else:  # pragma: no cover - the union above is exhaustive
            return event

        self._remember_item_id(event.item_id, event.output_index)
        self._rebuild(event.output_index)
        return event

    # Response envelope -----------------------------------------------------

    def _open(self, response: Response) -> None:
        self._envelope = response.model_copy(update={"output": ()})
        for output_index, item in enumerate(response.output):
            self._place_item(output_index, item, done=True)

    def _settle(self, event: ResponseSnapshotEventBase) -> Response:
        status = _TERMINAL_STATUS[event.type]
        snapshot = event.response
        for output_index, item in enumerate(snapshot.output):
            if output_index not in self._shells:
                self._place_item(output_index, item, done=True)
        base = self._envelope or snapshot
        self._envelope = snapshot.model_copy(
            update={
                "output": (),
                "status": status,
                "id": snapshot.id or base.id,
                "model": snapshot.model or base.model,
                "created_at": snapshot.created_at or base.created_at,
                "previous_response_id": snapshot.previous_response_id
                or base.previous_response_id,
            }
        )
        self._resolve_phases()
        return self.response or self._envelope

    def _fail(self, code: str, message: str) -> None:
        envelope = self._envelope or Response(status="failed")
        self._envelope = envelope.model_copy(
            update={
                "status": "failed",
                "error": ResponseError(code=code, message=message),
            }
        )

    def _resolve_phases(self) -> None:
        """Fill the optional ``phase`` of assistant messages once observable.

        A response that requested tools carries commentary; a response that
        requested none carries the answer. The specification requires ``phase``
        to be resent on follow-up requests, so resolving it here is what makes
        the replayed history complete when a provider omits the field.
        """

        phase = "commentary" if self._has_function_call() else "final_answer"
        for output_index, item in self._items.items():
            if (
                isinstance(item, MessageItem)
                and item.role == "assistant"
                and item.phase is None
            ):
                self._items[output_index] = item.model_copy(update={"phase": phase})
                shell = self._shells[output_index]
                self._shells[output_index] = shell.model_copy(update={"phase": phase})

    def _has_function_call(self) -> bool:
        return any(isinstance(item, FunctionCallItem) for item in self._items.values())

    # Items and parts -------------------------------------------------------

    def _place_item(self, output_index: int, item: Item, *, done: bool) -> None:
        status = getattr(item, "status", None) or ("completed" if done else "in_progress")
        shell = item.model_copy(update={"status": status})
        self._shells[output_index] = shell
        self._remember_item_id(getattr(shell, "id", None), output_index)
        self._seed(output_index, shell)
        self._rebuild(output_index)

    def _seed(self, output_index: int, item: Item) -> None:
        """Adopt any content an item already carries without losing deltas.

        ``response.output_item.added`` normally arrives with empty content and
        ``response.output_item.done`` may repeat the final text; either way a
        non-empty value replaces the accumulator and an empty one leaves the
        streamed deltas untouched.
        """

        if isinstance(item, MessageItem):
            for content_index, part in enumerate(item.content):
                self._place_part(output_index, content_index, part)
            return
        if isinstance(item, ReasoningItem):
            for content_index, part in enumerate(item.content):
                self._place_part(output_index, content_index, part)
            for summary_index, part in enumerate(item.summary):
                self._place_summary_part(output_index, summary_index, part)
            return
        if isinstance(item, FunctionCallItem):
            if item.arguments:
                self._arguments[output_index] = [item.arguments]
            else:
                self._arguments.setdefault(output_index, [])

    def _place_part(
        self, output_index: int, content_index: int, part: ContentPart
    ) -> None:
        key = (output_index, content_index)
        self._parts[key] = part
        text = getattr(part, "text", None) or getattr(part, "refusal", None)
        if text:
            self._text[key] = [text]
        else:
            self._text.setdefault(key, [])
        annotations = getattr(part, "annotations", ())
        if annotations:
            existing = self._annotations.setdefault(key, [])
            for annotation in annotations:
                if annotation not in existing:
                    existing.append(annotation)

    def _place_summary_part(
        self, output_index: int, summary_index: int, part: ContentPart
    ) -> None:
        key = (output_index, summary_index)
        self._summary_parts[key] = part
        text = getattr(part, "text", "")
        if text:
            self._summary_text[key] = [text]
        else:
            self._summary_text.setdefault(key, [])

    def _append_text(
        self,
        output_index: int,
        content_index: int,
        delta: str,
        shell: ContentPart,
    ) -> None:
        key = (output_index, content_index)
        self._parts.setdefault(key, shell)
        self._text.setdefault(key, []).append(delta)

    def _set_text(
        self,
        output_index: int,
        content_index: int,
        text: str,
        shell: ContentPart,
    ) -> None:
        key = (output_index, content_index)
        self._parts.setdefault(key, shell)
        self._text[key] = [text]

    def _add_annotation(
        self,
        output_index: int,
        content_index: int,
        annotation_index: int,
        annotation: Annotation,
    ) -> None:
        key = (output_index, content_index)
        self._parts.setdefault(key, OutputText(text=""))
        annotations = self._annotations.setdefault(key, [])
        position = min(annotation_index, len(annotations))
        annotations.insert(position, annotation)

    def _remember_item_id(self, item_id: str | None, output_index: int) -> None:
        if item_id:
            self._item_ids.setdefault(item_id, output_index)

    # Materialization -------------------------------------------------------

    def _rebuild(self, output_index: int) -> None:
        shell = self._shells.get(output_index)
        if shell is None:
            return
        if isinstance(shell, MessageItem):
            self._items[output_index] = shell.model_copy(
                update={"content": self._message_content(output_index)}
            )
            return
        if isinstance(shell, ReasoningItem):
            self._items[output_index] = shell.model_copy(
                update={
                    "content": self._reasoning_content(output_index),
                    "summary": self._reasoning_summary(output_index),
                }
            )
            return
        if isinstance(shell, FunctionCallItem):
            self._items[output_index] = shell.model_copy(
                update={"arguments": "".join(self._arguments.get(output_index, ()))}
            )
            return
        self._items[output_index] = shell

    def _message_content(self, output_index: int) -> tuple[ContentPart, ...]:
        return tuple(
            self._materialize_part(output_index, content_index)
            for content_index in self._content_indices(output_index)
        )

    def _reasoning_content(self, output_index: int) -> tuple[ContentPart, ...]:
        return tuple(
            self._materialize_part(output_index, content_index)
            for content_index in self._content_indices(output_index)
        )

    def _reasoning_summary(self, output_index: int) -> tuple[ContentPart, ...]:
        return tuple(
            SummaryText(text="".join(self._summary_text.get((output_index, index), ())))
            for index in sorted(
                summary_index
                for item_index, summary_index in self._summary_parts
                if item_index == output_index
            )
        )

    def _content_indices(self, output_index: int) -> list[int]:
        return sorted(
            content_index
            for item_index, content_index in self._parts
            if item_index == output_index
        )

    def _materialize_part(self, output_index: int, content_index: int) -> ContentPart:
        key = (output_index, content_index)
        part = self._parts[key]
        text = "".join(self._text.get(key, ()))
        if isinstance(part, OutputText):
            return OutputText(
                text=text, annotations=tuple(self._annotations.get(key, ()))
            )
        if isinstance(part, Refusal):
            return Refusal(refusal=text)
        if isinstance(part, ReasoningText):
            return ReasoningText(text=text)
        if isinstance(part, SummaryText):
            return SummaryText(text=text)
        return part


__all__ = ["ResponseReducer"]
