"""Tool declarations and tool-choice control.

Only function tools are modelled, because they are the one tool kind every
provider implements identically. Provider-hosted tools (web search, file
search, code interpreter) travel through :class:`ExtensionTool`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias, Union

from pydantic import Discriminator, Field, Tag, TypeAdapter, field_validator

from bothesis.agent.protocol import (
    EXTENSION_TAG,
    ExtensibleProtocolModel,
    ProtocolModel,
)

FUNCTION_TOOL_TYPE = "function"


class FunctionTool(ProtocolModel):
    """A callable function exposed to the model.

    ``parameters`` is a JSON Schema object. ``strict`` asks the provider to
    guarantee schema-valid arguments where it supports that mode.
    """

    type: Literal["function"] = "function"
    name: str = Field(min_length=1)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool = False


class ExtensionTool(ExtensibleProtocolModel):
    """A provider-hosted tool declared by its native type and fields."""

    type: str = Field(min_length=1)

    @field_validator("type")
    @classmethod
    def _reject_function(cls, value: str) -> str:
        if value == FUNCTION_TOOL_TYPE:
            raise ValueError("use FunctionTool for function tools")
        return value


def _tool_tag(value: Any) -> str:
    raw_type = (
        value.get("type") if isinstance(value, dict) else getattr(value, "type", None)
    )
    if raw_type == FUNCTION_TOOL_TYPE:
        return FUNCTION_TOOL_TYPE
    return EXTENSION_TAG


Tool: TypeAlias = Annotated[
    Union[
        Annotated[FunctionTool, Tag(FUNCTION_TOOL_TYPE)],
        Annotated[ExtensionTool, Tag(EXTENSION_TAG)],
    ],
    Discriminator(_tool_tag),
]

ToolAdapter: TypeAdapter[Tool] = TypeAdapter(Tool)

ToolChoiceMode: TypeAlias = Literal["none", "auto", "required"]


class FunctionToolChoice(ProtocolModel):
    """Force the model to call one named function."""

    type: Literal["function"] = "function"
    name: str = Field(min_length=1)


class ToolReference(ProtocolModel):
    """A pointer to a declared tool, used inside :class:`AllowedTools`."""

    type: str = FUNCTION_TOOL_TYPE
    name: str = Field(min_length=1)


class AllowedTools(ProtocolModel):
    """Restrict the model to a subset of the declared tools.

    ``mode`` keeps the OpenResponses meaning: ``auto`` lets the model answer
    directly or pick from the subset, ``required`` forces a call from it.
    """

    type: Literal["allowed_tools"] = "allowed_tools"
    mode: Literal["auto", "required"] = "auto"
    tools: tuple[ToolReference, ...] = Field(min_length=1)


ToolChoice: TypeAlias = Union[
    ToolChoiceMode,
    Annotated[
        Union[FunctionToolChoice, AllowedTools],
        Field(discriminator="type"),
    ],
]

__all__ = [
    "FUNCTION_TOOL_TYPE",
    "AllowedTools",
    "ExtensionTool",
    "FunctionTool",
    "FunctionToolChoice",
    "Tool",
    "ToolAdapter",
    "ToolChoice",
    "ToolChoiceMode",
    "ToolReference",
]
