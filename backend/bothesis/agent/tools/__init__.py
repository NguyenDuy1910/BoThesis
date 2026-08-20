from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from bothesis.agent.models import ToolContext, ToolOutput
from bothesis.agent.protocol import FunctionCallOutputItem, FunctionTool


JsonSchema = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Model-facing contract describing a tool."""

    name: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema | None = None
    defer_loading: bool = False
    activity_label: str | None = None
    activity_category: Literal["retrieval", "tool"] = "tool"


@dataclass(frozen=True, slots=True)
class ToolExecutionBatch:
    """Canonical observations and accounting from one completed tool round."""

    output_items: tuple[FunctionCallOutputItem, ...]
    duration_ms: int
    executed_call_count: int


class Tool(ABC):
    """A callable capability exposed to the model runtime."""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Describe the tool to the model."""
        raise NotImplementedError

    def as_function_tool(self) -> FunctionTool:
        """Project this tool's declaration onto the provider-neutral protocol."""

        definition = self.definition
        return FunctionTool(
            name=definition.name,
            description=definition.description,
            parameters=definition.input_schema,
            strict=True,
        )

    @abstractmethod
    async def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolOutput:
        """Execute the tool and return its output."""
        raise NotImplementedError


# The registry intentionally lives in its own module: this package contains
# shared tool contracts only, while each module owns one primary runtime type.
from bothesis.agent.tools.registry import ToolRegistry  # noqa: E402
from bothesis.agent.tools.executor import ToolExecutor  # noqa: E402


__all__ = [
    "JsonSchema",
    "Tool",
    "ToolDefinition",
    "ToolExecutionBatch",
    "ToolExecutor",
    "ToolRegistry",
]
