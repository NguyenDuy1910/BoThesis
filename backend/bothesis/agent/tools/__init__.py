from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from bothesis.agent.models import ConversationArtifact, ToolContext, ToolOutput
from bothesis.agent.protocol import FunctionCallOutputItem, FunctionTool
from bothesis.sandbox import SandboxError, SandboxOperationError
from bothesis.services import (
    ArtifactValidationError,
    AuthorizationError,
    DocumentNotFoundError,
)


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

    Validation, authorization, missing-document and sandbox-operation errors
    carry messages written for this purpose; anything else is left to the
    executor's generic failure path so no internal detail reaches the model.
    """

    if isinstance(exc, ArtifactValidationError):
        outcome = "invalid_input"
    elif isinstance(exc, DocumentNotFoundError):
        outcome = "not_found"
    elif isinstance(exc, AuthorizationError):
        outcome = "forbidden"
    elif isinstance(exc, SandboxOperationError):
        outcome = "operation_failed"
    elif isinstance(exc, SandboxError):
        return ToolOutput(
            content="",
            error="Document editing is temporarily unavailable. Please try again.",
            metadata={"outcome": "sandbox_unavailable", "result_count": 0},
        )
    else:
        return None
    return ToolOutput(
        content="",
        error=str(exc) or outcome,
        metadata={"outcome": outcome, "result_count": 0},
    )


def artifact_observation(
    artifact: ConversationArtifact,
    *,
    action: str,
    content: str | None,
    max_characters: int,
    guidance: str | None = None,
) -> ToolOutput:
    """Describe one produced revision to the model, with bounded content."""

    lines = [
        f'{action} "{artifact.title}" — artifact_id={artifact.id}, '
        f"revision {artifact.revision}, {artifact.file_name} "
        f"({format_size(artifact.size_bytes)})."
    ]
    if guidance:
        lines.append(guidance)
    if content:
        bounded = content
        truncated = False
        if len(bounded) > max_characters:
            bounded = f"{bounded[: max(1, max_characters - 1)].rstrip()}…"
            truncated = True
        lines.append(
            f'<artifact_content artifact_id="{artifact.id}" '
            f'revision="{artifact.revision}"'
            f'{" truncated=\"true\"" if truncated else ""}>'
        )
        lines.append(bounded)
        lines.append("</artifact_content>")
    return ToolOutput(
        content="\n".join(lines),
        metadata={
            "outcome": "success",
            "result_count": 1,
            "artifact_id": artifact.id,
            "revision": artifact.revision,
        },
        artifacts=(artifact,),
    )


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


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
    "artifact_observation",
    "format_size",
    "safe_tool_failure",
    "uuid_or_none",
]
