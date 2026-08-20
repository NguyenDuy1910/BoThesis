"""Small public item-lifecycle stream and private provider stream contracts."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, Union

from pydantic import Field, TypeAdapter

from bothesis.agent.protocol import ProtocolModel
from bothesis.agent.protocol.items import Item
from bothesis.agent.protocol.responses import Response


class StreamEventBase(ProtocolModel):
    """Base for an immutable streaming event."""


class TurnStarted(StreamEventBase):
    type: Literal["turn.started"] = "turn.started"


class ItemStarted(StreamEventBase):
    type: Literal["item.started"] = "item.started"
    item: Item


class ItemDelta(StreamEventBase):
    type: Literal["item.delta"] = "item.delta"
    item_id: str
    delta: str


class ItemCompleted(StreamEventBase):
    type: Literal["item.completed"] = "item.completed"
    item: Item


class TurnCompleted(StreamEventBase):
    type: Literal["turn.completed"] = "turn.completed"
    duration_ms: int | None = Field(default=None, ge=0)
    model_duration_ms: int | None = Field(default=None, ge=0)
    tool_duration_ms: int | None = Field(default=None, ge=0)
    tool_call_count: int | None = Field(default=None, ge=0)


class Error(StreamEventBase):
    type: Literal["error"] = "error"
    message: str


RuntimeStreamEvent: TypeAlias = Annotated[
    Union[
        TurnStarted,
        ItemStarted,
        ItemDelta,
        ItemCompleted,
        TurnCompleted,
        Error,
    ],
    Field(discriminator="type"),
]
RuntimeStreamEventAdapter: TypeAdapter[RuntimeStreamEvent] = TypeAdapter(RuntimeStreamEvent)


# Provider-native streams are normalized at the transport boundary only. They
# are intentionally distinct from the runtime stream consumed by the UI.
class ResponseCompletedEvent(StreamEventBase):
    type: Literal["response.completed"] = "response.completed"
    response: Response


class ResponseIncompleteEvent(StreamEventBase):
    type: Literal["response.incomplete"] = "response.incomplete"
    response: Response


class ResponseFailedEvent(StreamEventBase):
    type: Literal["response.failed"] = "response.failed"
    response: Response


class ResponseOutputItemDoneEvent(StreamEventBase):
    type: Literal["response.output_item.done"] = "response.output_item.done"
    output_index: int = Field(ge=0)
    item: Item


class ResponseOutputTextDeltaEvent(StreamEventBase):
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    item_id: str
    output_index: int = Field(ge=0)
    delta: str


class ResponseReasoningSummaryTextDeltaEvent(StreamEventBase):
    type: Literal["response.reasoning_summary_text.delta"] = "response.reasoning_summary_text.delta"
    item_id: str
    output_index: int = Field(ge=0)
    delta: str


ProviderStreamEvent: TypeAlias = Annotated[
    Union[
        ResponseCompletedEvent,
        ResponseIncompleteEvent,
        ResponseFailedEvent,
        ResponseOutputItemDoneEvent,
        ResponseOutputTextDeltaEvent,
        ResponseReasoningSummaryTextDeltaEvent,
    ],
    Field(discriminator="type"),
]
ProviderStreamEventAdapter: TypeAdapter[ProviderStreamEvent] = TypeAdapter(ProviderStreamEvent)


class ReasoningSummaryDelta:
    """One provider-authored public reasoning-summary fragment.

    This is an internal sampling event, not a UI runtime event. Raw reasoning
    text and encrypted reasoning must never be mapped to this type.
    """

    __slots__ = ("provider", "sampling_number", "item_id", "delta")

    def __init__(
        self,
        *,
        provider: Literal["openai", "openrouter"],
        sampling_number: int,
        item_id: str,
        delta: str,
    ) -> None:
        if sampling_number < 1:
            raise ValueError("sampling_number must be at least one")
        self.provider = provider
        self.sampling_number = sampling_number
        self.item_id = item_id
        self.delta = delta


__all__ = [
    "Error",
    "ItemCompleted",
    "ItemDelta",
    "ItemStarted",
    "ProviderStreamEvent",
    "ProviderStreamEventAdapter",
    "ReasoningSummaryDelta",
    "ResponseCompletedEvent",
    "ResponseFailedEvent",
    "ResponseIncompleteEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseReasoningSummaryTextDeltaEvent",
    "RuntimeStreamEvent",
    "RuntimeStreamEventAdapter",
    "StreamEventBase",
    "TurnCompleted",
    "TurnStarted",
]
