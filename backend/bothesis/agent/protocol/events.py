"""The OpenResponses server-sent event union.

Every event describes one mutation of the canonical :class:`Response` state,
never a UI command and never a runtime phase. The specification identifies the
target of a mutation with three indices and one id:

``output_index``
    which output item of the response is being mutated;
``content_index``
    which content part of that item;
``summary_index``
    which reasoning summary part of that item;
``item_id``
    the item's own id, which must agree with ``output_index``.

``sequence_number`` increases monotonically across the whole stream and is the
only ordering authority. A stream carries no response id on item-level events:
the response being mutated is the one opened by the most recent
``response.created``, and :attr:`Response.previous_response_id` chains the
several responses one agent turn may produce.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, Union

from pydantic import Field, TypeAdapter

from bothesis.agent.protocol import ProtocolModel
from bothesis.agent.protocol.content import (
    Annotation,
    ContentPart,
    ReasoningContent,
)
from bothesis.agent.protocol.items import Item
from bothesis.agent.protocol.responses import Response


class StreamEventBase(ProtocolModel):
    """Base for one replayable stream mutation."""

    sequence_number: int = Field(default=0, ge=0)


class ResponseSnapshotEventBase(StreamEventBase):
    """Base for the lifecycle events that carry the whole response."""

    response: Response


class ItemEventBase(StreamEventBase):
    """Base for the events that add or finalize a whole output item."""

    output_index: int = Field(ge=0)
    item: Item


class ContentEventBase(StreamEventBase):
    """Base for the events addressing one content part of one item."""

    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)


class SummaryEventBase(StreamEventBase):
    """Base for the events addressing one reasoning summary part."""

    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    summary_index: int = Field(ge=0)


class FunctionCallEventBase(StreamEventBase):
    """Base for the events streaming one function call's arguments."""

    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)


class ResponseCreatedEvent(ResponseSnapshotEventBase):
    type: Literal["response.created"] = "response.created"


class ResponseQueuedEvent(ResponseSnapshotEventBase):
    type: Literal["response.queued"] = "response.queued"


class ResponseInProgressEvent(ResponseSnapshotEventBase):
    type: Literal["response.in_progress"] = "response.in_progress"


class ResponseCompletedEvent(ResponseSnapshotEventBase):
    type: Literal["response.completed"] = "response.completed"


class ResponseIncompleteEvent(ResponseSnapshotEventBase):
    type: Literal["response.incomplete"] = "response.incomplete"


class ResponseFailedEvent(ResponseSnapshotEventBase):
    type: Literal["response.failed"] = "response.failed"


class ResponseOutputItemAddedEvent(ItemEventBase):
    type: Literal["response.output_item.added"] = "response.output_item.added"


class ResponseOutputItemDoneEvent(ItemEventBase):
    type: Literal["response.output_item.done"] = "response.output_item.done"


class ResponseContentPartAddedEvent(ContentEventBase):
    type: Literal["response.content_part.added"] = "response.content_part.added"
    part: ContentPart


class ResponseContentPartDoneEvent(ContentEventBase):
    type: Literal["response.content_part.done"] = "response.content_part.done"
    part: ContentPart


class ResponseOutputTextDeltaEvent(ContentEventBase):
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    delta: str


class ResponseOutputTextDoneEvent(ContentEventBase):
    type: Literal["response.output_text.done"] = "response.output_text.done"
    text: str


class ResponseOutputTextAnnotationAddedEvent(ContentEventBase):
    type: Literal["response.output_text.annotation.added"] = (
        "response.output_text.annotation.added"
    )
    annotation_index: int = Field(ge=0)
    annotation: Annotation


class ResponseRefusalDeltaEvent(ContentEventBase):
    type: Literal["response.refusal.delta"] = "response.refusal.delta"
    delta: str


class ResponseRefusalDoneEvent(ContentEventBase):
    type: Literal["response.refusal.done"] = "response.refusal.done"
    refusal: str


class ResponseReasoningDeltaEvent(ContentEventBase):
    type: Literal["response.reasoning.delta"] = "response.reasoning.delta"
    delta: str


class ResponseReasoningDoneEvent(ContentEventBase):
    type: Literal["response.reasoning.done"] = "response.reasoning.done"
    text: str


class ResponseReasoningSummaryPartAddedEvent(SummaryEventBase):
    type: Literal["response.reasoning_summary_part.added"] = (
        "response.reasoning_summary_part.added"
    )
    part: ReasoningContent


class ResponseReasoningSummaryPartDoneEvent(SummaryEventBase):
    type: Literal["response.reasoning_summary_part.done"] = (
        "response.reasoning_summary_part.done"
    )
    part: ReasoningContent


class ResponseReasoningSummaryTextDeltaEvent(SummaryEventBase):
    type: Literal["response.reasoning_summary_text.delta"] = (
        "response.reasoning_summary_text.delta"
    )
    delta: str


class ResponseReasoningSummaryTextDoneEvent(SummaryEventBase):
    type: Literal["response.reasoning_summary_text.done"] = (
        "response.reasoning_summary_text.done"
    )
    text: str


class ResponseFunctionCallArgumentsDeltaEvent(FunctionCallEventBase):
    type: Literal["response.function_call_arguments.delta"] = (
        "response.function_call_arguments.delta"
    )
    delta: str


class ResponseFunctionCallArgumentsDoneEvent(FunctionCallEventBase):
    type: Literal["response.function_call_arguments.done"] = (
        "response.function_call_arguments.done"
    )
    arguments: str


class ErrorPayload(ProtocolModel):
    """The error body of a streaming ``error`` event."""

    type: str = "error"
    message: str
    code: str | None = None
    param: str | None = None


class ErrorEvent(StreamEventBase):
    """A stream-level error that is not attached to a response snapshot."""

    type: Literal["error"] = "error"
    error: ErrorPayload


ResponseStreamEvent: TypeAlias = Annotated[
    Union[
        ResponseCreatedEvent,
        ResponseQueuedEvent,
        ResponseInProgressEvent,
        ResponseCompletedEvent,
        ResponseIncompleteEvent,
        ResponseFailedEvent,
        ResponseOutputItemAddedEvent,
        ResponseOutputItemDoneEvent,
        ResponseContentPartAddedEvent,
        ResponseContentPartDoneEvent,
        ResponseOutputTextDeltaEvent,
        ResponseOutputTextDoneEvent,
        ResponseOutputTextAnnotationAddedEvent,
        ResponseRefusalDeltaEvent,
        ResponseRefusalDoneEvent,
        ResponseReasoningDeltaEvent,
        ResponseReasoningDoneEvent,
        ResponseReasoningSummaryPartAddedEvent,
        ResponseReasoningSummaryPartDoneEvent,
        ResponseReasoningSummaryTextDeltaEvent,
        ResponseReasoningSummaryTextDoneEvent,
        ResponseFunctionCallArgumentsDeltaEvent,
        ResponseFunctionCallArgumentsDoneEvent,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]

ResponseStreamEventAdapter: TypeAdapter[ResponseStreamEvent] = TypeAdapter(
    ResponseStreamEvent
)

TERMINAL_EVENT_TYPES = frozenset(
    {"response.completed", "response.incomplete", "response.failed"}
)
"""The event types that settle one response."""


__all__ = [
    "TERMINAL_EVENT_TYPES",
    "ContentEventBase",
    "ErrorEvent",
    "ErrorPayload",
    "FunctionCallEventBase",
    "ItemEventBase",
    "ResponseCompletedEvent",
    "ResponseContentPartAddedEvent",
    "ResponseContentPartDoneEvent",
    "ResponseCreatedEvent",
    "ResponseFailedEvent",
    "ResponseFunctionCallArgumentsDeltaEvent",
    "ResponseFunctionCallArgumentsDoneEvent",
    "ResponseInProgressEvent",
    "ResponseIncompleteEvent",
    "ResponseOutputItemAddedEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseOutputTextAnnotationAddedEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseOutputTextDoneEvent",
    "ResponseQueuedEvent",
    "ResponseReasoningDeltaEvent",
    "ResponseReasoningDoneEvent",
    "ResponseReasoningSummaryPartAddedEvent",
    "ResponseReasoningSummaryPartDoneEvent",
    "ResponseReasoningSummaryTextDeltaEvent",
    "ResponseReasoningSummaryTextDoneEvent",
    "ResponseRefusalDeltaEvent",
    "ResponseRefusalDoneEvent",
    "ResponseSnapshotEventBase",
    "ResponseStreamEvent",
    "ResponseStreamEventAdapter",
    "StreamEventBase",
    "SummaryEventBase",
]
