"""The provider-neutral semantic stream consumed by BoThesis clients.

The public stream deliberately follows the OpenAI Responses lifecycle. A
``response.completed`` event settles one sampling request, not the enclosing
agent Turn; a Turn may create another response after function execution.
Clients materialize response and item state from these events rather than
interpreting runtime phases or UI commands.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, Union

from pydantic import Field, TypeAdapter, model_validator

from bothesis.agent.protocol import ProtocolModel
from bothesis.agent.protocol.content import ContentPart
from bothesis.agent.protocol.items import Item
from bothesis.agent.protocol.responses import Response


class StreamEventBase(ProtocolModel):
    """Base for one replayable public stream mutation."""

    sequence_number: int = Field(default=0, ge=0)


class ResponseCreatedEvent(StreamEventBase):
    type: Literal["response.created"] = "response.created"
    response_id: str = Field(min_length=1)
    response: Response

    @model_validator(mode="after")
    def _match_response_id(self) -> "ResponseCreatedEvent":
        if self.response.id != self.response_id:
            raise ValueError("response_id must match response.id")
        return self


class ResponseOutputItemAddedEvent(StreamEventBase):
    type: Literal["response.output_item.added"] = "response.output_item.added"
    response_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    item: Item


class ResponseContentPartAddedEvent(StreamEventBase):
    type: Literal["response.content_part.added"] = "response.content_part.added"
    response_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    part: ContentPart


class ResponseOutputTextDeltaEvent(StreamEventBase):
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    response_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    delta: str


class ResponseContentPartDoneEvent(StreamEventBase):
    type: Literal["response.content_part.done"] = "response.content_part.done"
    response_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    part: ContentPart


class ResponseOutputTextDoneEvent(StreamEventBase):
    type: Literal["response.output_text.done"] = "response.output_text.done"
    response_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    text: str


class ResponseFunctionCallArgumentsDeltaEvent(StreamEventBase):
    type: Literal["response.function_call_arguments.delta"] = (
        "response.function_call_arguments.delta"
    )
    response_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    delta: str


class ResponseFunctionCallArgumentsDoneEvent(StreamEventBase):
    type: Literal["response.function_call_arguments.done"] = (
        "response.function_call_arguments.done"
    )
    response_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    arguments: str


class ResponseOutputTextAnnotationAddedEvent(StreamEventBase):
    type: Literal["response.output_text.annotation.added"] = (
        "response.output_text.annotation.added"
    )
    response_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    annotation: dict[str, object]


class ResponseOutputItemDoneEvent(StreamEventBase):
    type: Literal["response.output_item.done"] = "response.output_item.done"
    response_id: str = Field(min_length=1)
    output_index: int = Field(ge=0)
    item: Item


class ResponseCompletedEvent(StreamEventBase):
    type: Literal["response.completed"] = "response.completed"
    response: Response


class ResponseIncompleteEvent(StreamEventBase):
    type: Literal["response.incomplete"] = "response.incomplete"
    response: Response


class ResponseFailedEvent(StreamEventBase):
    type: Literal["response.failed"] = "response.failed"
    response: Response


ResponseStreamEvent: TypeAlias = Annotated[
    Union[
        ResponseCreatedEvent,
        ResponseOutputItemAddedEvent,
        ResponseContentPartAddedEvent,
        ResponseOutputTextDeltaEvent,
        ResponseContentPartDoneEvent,
        ResponseOutputTextDoneEvent,
        ResponseFunctionCallArgumentsDeltaEvent,
        ResponseFunctionCallArgumentsDoneEvent,
        ResponseOutputTextAnnotationAddedEvent,
        ResponseOutputItemDoneEvent,
        ResponseCompletedEvent,
        ResponseIncompleteEvent,
        ResponseFailedEvent,
    ],
    Field(discriminator="type"),
]
ResponseStreamEventAdapter: TypeAdapter[ResponseStreamEvent] = TypeAdapter(ResponseStreamEvent)


__all__ = [
    "ResponseCompletedEvent",
    "ResponseContentPartAddedEvent",
    "ResponseContentPartDoneEvent",
    "ResponseCreatedEvent",
    "ResponseFailedEvent",
    "ResponseFunctionCallArgumentsDeltaEvent",
    "ResponseFunctionCallArgumentsDoneEvent",
    "ResponseIncompleteEvent",
    "ResponseOutputItemAddedEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseOutputTextAnnotationAddedEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseOutputTextDoneEvent",
    "ResponseStreamEvent",
    "ResponseStreamEventAdapter",
    "StreamEventBase",
]
