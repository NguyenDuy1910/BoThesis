from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from bothesis.agent.models import ToolOutput
from bothesis.agent.protocol import FunctionCallOutputItem, FunctionTool
from bothesis.services import (
    ArtifactValidationError,
    AuthorizationError,
    DocumentNotFoundError,
)


if TYPE_CHECKING:
    from bothesis.agent import Session, StepContext, TurnContext

JsonSchema = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
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


class ToolExposure(StrEnum):
    DIRECT = "direct"
    DEFERRED = "deferred"
    HIDDEN = "hidden"


class ToolCallSource(StrEnum):
    MODEL = "model"
    RUNTIME = "runtime"


@dataclass(frozen=True, slots=True)
class ToolPayload:
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """A normalized call bound to the StepContext that exposed its tool."""

    session: "Session"
    turn: "TurnContext"
    step_context: "StepContext"
    call_id: str
    tool_name: str
    source: ToolCallSource
    payload: ToolPayload

    @property
    def agent_context(self) -> Any:
        return self.step_context.environment.agent_context

    @property
    def references(self) -> Any:
        return self.turn.references


class ToolExecutor(ABC):
    """A model-visible declaration and its executable implementation."""

    def spec(self) -> ToolSpec:
        """Describe the tool to the model."""
        raise NotImplementedError

    def exposure(self) -> ToolExposure:
        return ToolExposure.DIRECT

    def supports_parallel_tool_calls(self) -> bool:
        return True

    def as_function_tool(self) -> FunctionTool:
        """Project this tool's declaration onto the provider-neutral protocol."""

        definition = self.spec()
        return FunctionTool(
            name=definition.name,
            description=definition.description,
            parameters=definition.input_schema,
            strict=True,
        )

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        """Execute the tool and return its output."""
        raise NotImplementedError


def uuid_or_none(value: object) -> UUID | None:
    """Parse a model- or client-supplied identifier without trusting it."""

    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value.strip())
    except ValueError:
        return None


def safe_tool_failure(exc: Exception) -> ToolOutput | None:
    """Turn a failure the model can act on into an observation, else ``None``.

    Validation, authorization and missing-document errors carry messages
    written for this purpose; anything else is left to the executor's generic
    failure path so no internal detail reaches the model.
    """

    if isinstance(exc, ArtifactValidationError):
        outcome = "invalid_input"
    elif isinstance(exc, DocumentNotFoundError):
        outcome = "not_found"
    elif isinstance(exc, AuthorizationError):
        outcome = "forbidden"
    else:
        return None
    return ToolOutput(
        content="",
        error=str(exc) or outcome,
        metadata={"outcome": outcome, "result_count": 0},
    )


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


# The registry intentionally lives in its own module: this package contains
# shared tool contracts only, while each module owns one primary runtime type.
from bothesis.agent.tools.orchestrator import ToolOrchestrator  # noqa: E402
from bothesis.agent.tools.registry import ToolRegistry  # noqa: E402
from bothesis.agent.tools.router import ToolRouter  # noqa: E402


__all__ = [
    "JsonSchema",
    "ToolCallSource",
    "ToolExecutor",
    "ToolExecutionBatch",
    "ToolExposure",
    "ToolInvocation",
    "ToolOrchestrator",
    "ToolPayload",
    "ToolRouter",
    "ToolRegistry",
    "ToolSpec",
    "format_size",
    "safe_tool_failure",
    "uuid_or_none",
]
