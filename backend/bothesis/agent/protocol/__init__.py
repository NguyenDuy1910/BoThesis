"""Provider-neutral response protocol modelled on the OpenResponses shape.

The protocol is the contract between the agent runtime and any provider
transport. It deliberately mirrors OpenResponses naming and semantics so a
native OpenAI or OpenRouter transport needs field mapping only, never
structural translation.

``Item`` is the primitive: a request carries a collection of input items and a
response carries a collection of output items. Provider-specific concepts stay
out of the common contract and travel through the two escape hatches:
``ExtensionItem``/``ExtensionTool`` for unknown item and tool types, and
``ResponseRequest.provider_options`` for opaque request options.

This package must never import a provider SDK.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# Tag used by the callable discriminators for any unrecognized item or tool
# type. It is never a wire value; the original ``type`` string is preserved.
EXTENSION_TAG = "__extension__"


class ProtocolModel(BaseModel):
    """Immutable, strictly validated base for every protocol model.

    Extra fields are rejected so transport mapping bugs surface at the
    boundary instead of silently dropping provider data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ExtensibleProtocolModel(ProtocolModel):
    """Base for escape hatches that must round-trip unknown provider fields."""

    model_config = ConfigDict(frozen=True, extra="allow")


# Submodules import the shared base from this package while they are being
# imported, so the primary contracts are re-exported only after it exists.
from bothesis.agent.protocol.content import (  # noqa: E402
    ContentPart,
    InputContent,
    InputFile,
    InputImage,
    InputText,
    OutputContent,
    OutputText,
    Refusal,
)
from bothesis.agent.protocol.events import (  # noqa: E402
    Error,
    ItemCompleted,
    ItemDelta,
    ItemStarted,
    ProviderStreamEvent,
    ProviderStreamEventAdapter,
    ReasoningSummaryDelta,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    RuntimeStreamEvent,
    RuntimeStreamEventAdapter,
    StreamEventBase,
    TurnCompleted,
    TurnStarted,
)
from bothesis.agent.protocol.items import (  # noqa: E402
    CORE_ITEM_TYPES,
    EvidenceItem,
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
    ReasoningSummaryText,
    ToolCallItem,
    ToolExecutionStatus,
    ToolResultItem,
    pair_function_calls,
)
from bothesis.agent.protocol.responses import (  # noqa: E402
    IncompleteDetails,
    InputTokensDetails,
    OutputTokensDetails,
    Response,
    ResponseError,
    ResponseRequest,
    ResponseStatus,
    ResponseUsage,
)
from bothesis.agent.protocol.models import SamplingRequestOutput  # noqa: E402
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

__all__ = [
    "CORE_ITEM_TYPES",
    "EXTENSION_TAG",
    "AllowedTools",
    "ContentPart",
    "Error",
    "EvidenceItem",
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
    "ItemCompleted",
    "ItemDelta",
    "ItemStarted",
    "ItemStatus",
    "MessageItem",
    "MessagePhase",
    "MessageRole",
    "OutputContent",
    "OutputText",
    "OutputTokensDetails",
    "ProtocolModel",
    "ProviderStreamEvent",
    "ProviderStreamEventAdapter",
    "ReasoningSummaryDelta",
    "ReasoningItem",
    "ReasoningSummaryText",
    "Refusal",
    "Response",
    "ResponseCompletedEvent",
    "ResponseError",
    "ResponseFailedEvent",
    "ResponseIncompleteEvent",
    "ResponseOutputItemDoneEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseReasoningSummaryTextDeltaEvent",
    "ResponseRequest",
    "ResponseStatus",
    "RuntimeStreamEvent",
    "RuntimeStreamEventAdapter",
    "ResponseUsage",
    "SamplingRequestOutput",
    "StreamEventBase",
    "Tool",
    "ToolAdapter",
    "ToolChoice",
    "ToolChoiceMode",
    "ToolCallItem",
    "ToolExecutionStatus",
    "ToolReference",
    "ToolResultItem",
    "TurnCompleted",
    "TurnStarted",
    "pair_function_calls",
]
