"""Semantic streaming events for one response.

Event names and payload fields follow OpenResponses so a transport can map a
provider stream without inventing its own vocabulary. Lifecycle events carry
the whole :class:`Response` snapshot; item and delta events carry the indices
needed to attach a fragment to the item it belongs to.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, Union

from pydantic import Field, TypeAdapter

from bothesis.agent.protocol import ProtocolModel
from bothesis.agent.protocol.items import Item
from bothesis.agent.protocol.responses import Response


class StreamEventBase(ProtocolModel):
    """Fields shared by every streaming event."""

    sequence_number: int = Field(ge=0)


class ResponseCreatedEvent(StreamEventBase):
    type: Literal["response.created"] = "response.created"
    response: Response


class ResponseInProgressEvent(StreamEventBase):
    type: Literal["response.in_progress"] = "response.in_progress"
    response: Response


class ResponseCompletedEvent(StreamEventBase):
    type: Literal["response.completed"] = "response.completed"
    response: Response


class ResponseIncompleteEvent(StreamEventBase):
    type: Literal["response.incomplete"] = "response.incomplete"
    response: Response


class ResponseFailedEvent(StreamEventBase):
    type: Literal["response.failed"] = "response.failed"
    response: Response


class ResponseOutputItemAddedEvent(StreamEventBase):
    type: Literal["response.output_item.added"] = "response.output_item.added"
    output_index: int = Field(ge=0)
    item: Item


class ResponseOutputItemDoneEvent(StreamEventBase):
    type: Literal["response.output_item.done"] = "response.output_item.done"
    output_index: int = Field(ge=0)
    item: Item


class ResponseOutputTextDeltaEvent(StreamEventBase):
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    item_id: str
    output_index: int = Field(ge=0)
    content_index: int = Field(default=0, ge=0)
    delta: str


class ResponseOutputTextDoneEvent(StreamEventBase):
    type: Literal["response.output_text.done"] = "response.output_text.done"
    item_id: str
    output_index: int = Field(ge=0)
    content_index: int = Field(default=0, ge=0)
    text: str


class ResponseFunctionCallArgumentsDeltaEvent(StreamEventBase):
    type: Literal["response.function_call_arguments.delta"] = (
        "response.function_call_arguments.delta"
    )
    item_id: str
    output_index: int = Field(ge=0)
    delta: str


class ResponseFunctionCallArgumentsDoneEvent(StreamEventBase):
    type: Literal["response.function_call_arguments.done"] = (
        "response.function_call_arguments.done"
    )
    item_id: str
    output_index: int = Field(ge=0)
    arguments: str


class ResponseReasoningSummaryTextDeltaEvent(StreamEventBase):
    type: Literal["response.reasoning_summary_text.delta"] = (
        "response.reasoning_summary_text.delta"
    )
    item_id: str
    output_index: int = Field(ge=0)
    summary_index: int = Field(default=0, ge=0)
    delta: str


class ResponseReasoningSummaryTextDoneEvent(StreamEventBase):
    type: Literal["response.reasoning_summary_text.done"] = (
        "response.reasoning_summary_text.done"
    )
    item_id: str
    output_index: int = Field(ge=0)
    summary_index: int = Field(default=0, ge=0)
    text: str


ResponseStreamEvent: TypeAlias = Annotated[
    Union[
        ResponseCreatedEvent,
        ResponseInProgressEvent,
        ResponseCompletedEvent,
        ResponseIncompleteEvent,
        ResponseFailedEvent,
        ResponseOutputItemAddedEvent,
        ResponseOutputItemDoneEvent,
        ResponseOutputTextDeltaEvent,
        ResponseOutputTextDoneEvent,
        ResponseFunctionCallArgumentsDeltaEvent,
        ResponseFunctionCallArgumentsDoneEvent,
        ResponseReasoningSummaryTextDeltaEvent,
        ResponseReasoningSummaryTextDoneEvent,
    ],
    Field(discriminator="type"),
]

ResponseStreamEventAdapter: TypeAdapter[ResponseStreamEvent] = TypeAdapter(
    ResponseStreamEvent
)

__all__ = [
    "ResponseCompletedEvent",
    "ResponseCreatedEvent",
    "ResponseFailedEvent",
    "ResponseFunctionCallArgumentsDeltaEvent",
    "ResponseFunctionCallArgumentsDoneEvent",
    "ResponseInProgressEvent",
    "ResponseIncompleteEvent",
    "ResponseOutputItemAddedEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseOutputTextDoneEvent",
    "ResponseReasoningSummaryTextDeltaEvent",
    "ResponseReasoningSummaryTextDoneEvent",
    "ResponseStreamEvent",
    "ResponseStreamEventAdapter",
    "StreamEventBase",
]
