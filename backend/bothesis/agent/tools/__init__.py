from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from bothesis.agent.models import ToolContext, ToolOutput


JsonSchema = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Model-facing contract describing a tool."""

    name: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema | None = None
    defer_loading: bool = False


class Tool(ABC):
    """A callable capability exposed to the model runtime."""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Describe the tool to the model."""
        raise NotImplementedError

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


__all__ = [
    "JsonSchema",
    "Tool",
    "ToolDefinition",
    "ToolRegistry",
]
