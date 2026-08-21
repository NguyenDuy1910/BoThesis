"""OpenResponses data contracts — and nothing else.

This package is the canonical language of the agent. It mirrors the
OpenResponses specification (https://www.openresponses.org, version
2026-04-24): a :class:`~bothesis.agent.protocol.responses.Response` owns an
ordered ``output`` of Items, an Item owns ContentParts, and the streaming
events describe mutations of exactly that state.

The package holds no behaviour. Response reconstruction lives in
:mod:`bothesis.agent.reducer`, provider communication and normalization in
:mod:`bothesis.agent.transports`, and orchestration in
:mod:`bothesis.agent.conversation_loop`. This package must never import a
provider SDK.

Two escape hatches keep implementer concepts out of the common contract:
:class:`~bothesis.agent.protocol.items.ExtensionItem` /
:class:`~bothesis.agent.protocol.tools.ExtensionTool` for slug-prefixed
implementer types, and ``ResponseRequest.provider_options`` for opaque request
options.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# Tag used by the callable discriminators for any item or tool type outside the
# specification. It is never a wire value; the original ``type`` is preserved.
EXTENSION_TAG = "__extension__"


class ProtocolModel(BaseModel):
    """Immutable, strictly validated base for every protocol model.

    Extra fields are rejected so adapter mapping bugs surface at the provider
    boundary instead of silently dropping data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ExtensibleProtocolModel(ProtocolModel):
    """Base for escape hatches that must round-trip unknown provider fields."""

    model_config = ConfigDict(frozen=True, extra="allow")


# Submodules import the shared base from this package while they are being
# imported, so the primary contracts are re-exported only after it exists.
from bothesis.agent.protocol.content import (  # noqa: E402
    DOCUMENT_CITATION_TYPE,
    TEXT_PART_TYPES,
    Annotation,
    ContentPart,
    InputContent,
    InputFile,
    InputImage,
    InputText,
    MessageOutputContent,
    OutputText,
    ReasoningContent,
    ReasoningText,
    Refusal,
    SummaryText,
)
from bothesis.agent.protocol.items import (  # noqa: E402
    CORE_ITEM_TYPES,
    CompactionItem,
    ExtensionItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    Item,
    ItemAdapter,
    ItemStatus,
    MessageItem,
    MessagePhase,
    MessageRole,
    ReasoningItem,
)
from bothesis.agent.protocol.tools import (  # noqa: E402
    AllowedTools,
    ExtensionTool,
    FunctionTool,
    FunctionToolChoice,
    Tool,
    ToolAdapter,
    ToolChoice,
    ToolChoiceMode,
    ToolReference,
)
from bothesis.agent.protocol.responses import (  # noqa: E402
    TERMINAL_RESPONSE_STATUSES,
    IncompleteDetails,
    InputTokensDetails,
    OutputTokensDetails,
    Response,
    ResponseError,
    ResponseRequest,
    ResponseStatus,
    ResponseUsage,
)
from bothesis.agent.protocol.events import (  # noqa: E402
    TERMINAL_EVENT_TYPES,
    ErrorEvent,
    ErrorPayload,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
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
    ResponseStreamEventAdapter,
    StreamEventBase,
)

__all__ = [
    "CORE_ITEM_TYPES",
    "DOCUMENT_CITATION_TYPE",
    "EXTENSION_TAG",
    "TERMINAL_EVENT_TYPES",
    "TERMINAL_RESPONSE_STATUSES",
    "TEXT_PART_TYPES",
    "AllowedTools",
    "Annotation",
    "CompactionItem",
    "ContentPart",
    "ErrorEvent",
    "ErrorPayload",
    "ExtensibleProtocolModel",
    "ExtensionItem",
    "ExtensionTool",
    "FunctionCallItem",
    "FunctionCallOutputItem",
    "FunctionTool",
    "FunctionToolChoice",
    "IncompleteDetails",
    "InputContent",
    "InputFile",
    "InputImage",
    "InputText",
    "InputTokensDetails",
    "Item",
    "ItemAdapter",
    "ItemStatus",
    "MessageItem",
    "MessageOutputContent",
    "MessagePhase",
    "MessageRole",
    "OutputText",
    "OutputTokensDetails",
    "ProtocolModel",
    "ReasoningContent",
    "ReasoningItem",
    "ReasoningText",
    "Refusal",
    "Response",
    "ResponseCompletedEvent",
    "ResponseContentPartAddedEvent",
    "ResponseContentPartDoneEvent",
    "ResponseCreatedEvent",
    "ResponseError",
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
    "ResponseRequest",
    "ResponseSnapshotEventBase",
    "ResponseStatus",
    "ResponseStreamEvent",
    "ResponseStreamEventAdapter",
    "ResponseUsage",
    "StreamEventBase",
    "SummaryText",
    "Tool",
    "ToolAdapter",
    "ToolChoice",
    "ToolChoiceMode",
    "ToolReference",
]
