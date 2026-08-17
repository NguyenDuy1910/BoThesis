from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, TypeAlias, Union

from pydantic import Discriminator, Field, Tag, TypeAdapter, field_validator

from bothesis.agent.protocol import (
    EXTENSION_TAG,
    ExtensibleProtocolModel,
    ProtocolModel,
)
from bothesis.agent.protocol.content import ContentPart, InputText, OutputText

ItemStatus: TypeAlias = Literal["in_progress", "completed", "incomplete"]
MessageRole: TypeAlias = Literal["system", "developer", "user", "assistant"]

CORE_ITEM_TYPES = frozenset(
    {"message", "reasoning", "function_call", "function_call_output"}
)


class MessageItem(ProtocolModel):
    """One conversation message addressed to or produced by the model."""

    type: Literal["message"] = "message"
    role: MessageRole
    content: tuple[ContentPart, ...]
    id: str | None = None
    status: ItemStatus | None = None

    @property
    def text(self) -> str:
        """Concatenate the textual parts, ignoring images, files, and refusals."""

        return "".join(
            part.text
            for part in self.content
            if isinstance(part, (InputText, OutputText))
        )


class ReasoningSummaryText(ProtocolModel):
    """One provider-authored reasoning summary fragment."""

    type: Literal["summary_text"] = "summary_text"
    text: str


class ReasoningItem(ProtocolModel):
    """A reasoning item exposing only the provider's public summary.

    Raw chain-of-thought is never modelled. ``encrypted_content`` carries the
    opaque blob a provider requires to continue a reasoning session.
    """

    type: Literal["reasoning"] = "reasoning"
    id: str | None = None
    summary: tuple[ReasoningSummaryText, ...] = ()
    encrypted_content: str | None = None
    status: ItemStatus | None = None

    @property
    def summary_text(self) -> str:
        return "".join(part.text for part in self.summary)


class FunctionCallItem(ProtocolModel):
    """A model request to call one function tool.

    ``arguments`` stays the JSON string the provider emitted so nothing is lost
    when the item is echoed back on the next turn. Use :meth:`parsed_arguments`
    to decode it.
    """

    type: Literal["function_call"] = "function_call"
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str = ""
    id: str | None = None
    status: ItemStatus | None = None

    def parsed_arguments(self) -> dict[str, Any]:
        """Decode ``arguments`` into a JSON object.

        Raises ``ValueError`` when the model produced invalid JSON or a
        non-object, so callers can turn it into a tool observation instead of
        guessing what the model meant.
        """

        if not self.arguments.strip():
            return {}
        try:
            value = json.loads(self.arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"function call arguments are not valid JSON: {self.name}"
            ) from exc
        if not isinstance(value, Mapping):
            raise ValueError(
                f"function call arguments are not a JSON object: {self.name}"
            )
        return dict(value)


class FunctionCallOutputItem(ProtocolModel):
    """The observation returned for one ``function_call``."""

    type: Literal["function_call_output"] = "function_call_output"
    call_id: str = Field(min_length=1)
    output: str
    id: str | None = None
    status: ItemStatus | None = None


class ExtensionItem(ExtensibleProtocolModel):
    """A provider-specific item preserved verbatim.

    This is the item-level escape hatch. It accepts any ``type`` outside
    :data:`CORE_ITEM_TYPES` and keeps every additional field, so provider
    concepts the protocol does not model can still be replayed to that
    provider on later turns.
    """

    type: str = Field(min_length=1)
    id: str | None = None

    @field_validator("type")
    @classmethod
    def _reject_core_types(cls, value: str) -> str:
        if value in CORE_ITEM_TYPES:
            raise ValueError(f"{value} is a core protocol item type")
        return value


def _item_tag(value: Any) -> str:
    """Route core item types to their model and anything else to the hatch."""

    raw_type = (
        value.get("type")
        if isinstance(value, Mapping)
        else getattr(value, "type", None)
    )
    if isinstance(raw_type, str) and raw_type in CORE_ITEM_TYPES:
        return raw_type
    return EXTENSION_TAG


Item: TypeAlias = Annotated[
    Union[
        Annotated[MessageItem, Tag("message")],
        Annotated[ReasoningItem, Tag("reasoning")],
        Annotated[FunctionCallItem, Tag("function_call")],
        Annotated[FunctionCallOutputItem, Tag("function_call_output")],
        Annotated[ExtensionItem, Tag(EXTENSION_TAG)],
    ],
    Discriminator(_item_tag),
]

ItemAdapter: TypeAdapter[Item] = TypeAdapter(Item)


def pair_function_calls(
    items: Sequence[Item],
) -> tuple[tuple[FunctionCallItem, FunctionCallOutputItem | None], ...]:
    """Correlate every ``function_call`` with its output by ``call_id``.

    Calls still awaiting an observation pair with ``None``, which is how an
    unfinished tool round is represented.
    """

    outputs = {
        item.call_id: item for item in items if isinstance(item, FunctionCallOutputItem)
    }
    return tuple(
        (item, outputs.get(item.call_id))
        for item in items
        if isinstance(item, FunctionCallItem)
    )


__all__ = [
    "CORE_ITEM_TYPES",
    "ExtensionItem",
    "FunctionCallItem",
    "FunctionCallOutputItem",
    "Item",
    "ItemAdapter",
    "ItemStatus",
    "MessageItem",
    "MessageRole",
    "ReasoningItem",
    "ReasoningSummaryText",
    "pair_function_calls",
]
