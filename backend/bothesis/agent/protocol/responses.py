"""The request and response envelopes around protocol items."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import Field

from bothesis.agent.protocol import ProtocolModel
from bothesis.agent.protocol.content import OutputText
from bothesis.agent.protocol.items import FunctionCallItem, Item, MessageItem
from bothesis.agent.protocol.tools import Tool, ToolChoice

ResponseStatus: TypeAlias = Literal[
    "queued",
    "in_progress",
    "completed",
    "incomplete",
    "failed",
    "cancelled",
]


class InputTokensDetails(ProtocolModel):
    cached_tokens: int = 0


class OutputTokensDetails(ProtocolModel):
    reasoning_tokens: int = 0


class ResponseUsage(ProtocolModel):
    """Token accounting for one response."""

    input_tokens: int = 0
    input_tokens_details: InputTokensDetails = Field(default_factory=InputTokensDetails)
    output_tokens: int = 0
    output_tokens_details: OutputTokensDetails = Field(
        default_factory=OutputTokensDetails
    )
    total_tokens: int = 0


class ResponseError(ProtocolModel):
    """Why a response reached the ``failed`` status."""

    code: str
    message: str


class IncompleteDetails(ProtocolModel):
    """Why a response reached the ``incomplete`` status."""

    reason: str


class ResponseRequest(ProtocolModel):
    """One provider-neutral model request.

    ``provider_options`` is the request-level escape hatch: transports merge it
    into the native request body verbatim, which keeps provider-only knobs
    (reasoning effort, routing preferences, caching hints) out of the common
    contract.
    """

    input: tuple[Item, ...]
    model: str | None = None
    instructions: str | None = None
    tools: tuple[Tool, ...] = ()
    tool_choice: ToolChoice | None = None
    parallel_tool_calls: bool | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    previous_response_id: str | None = None
    store: bool | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)


class Response(ProtocolModel):
    """One model response as an ordered collection of output items."""

    status: ResponseStatus
    id: str = ""
    created_at: int = 0
    model: str | None = None
    output: tuple[Item, ...] = ()
    usage: ResponseUsage | None = None
    error: ResponseError | None = None
    incomplete_details: IncompleteDetails | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def output_text(self) -> str:
        """Concatenate the text of every assistant message item."""

        return "".join(
            item.text for item in self.output if isinstance(item, MessageItem)
        )

    @property
    def function_calls(self) -> tuple[FunctionCallItem, ...]:
        """Return the function calls the model requested, in output order."""

        return tuple(item for item in self.output if isinstance(item, FunctionCallItem))

    @property
    def output_annotations(self) -> tuple[dict[str, Any], ...]:
        """Flatten the annotations attached to every output text part."""

        return tuple(
            annotation
            for item in self.output
            if isinstance(item, MessageItem)
            for part in item.content
            if isinstance(part, OutputText)
            for annotation in part.annotations
        )


__all__ = [
    "IncompleteDetails",
    "InputTokensDetails",
    "OutputTokensDetails",
    "Response",
    "ResponseError",
    "ResponseRequest",
    "ResponseStatus",
    "ResponseUsage",
]
