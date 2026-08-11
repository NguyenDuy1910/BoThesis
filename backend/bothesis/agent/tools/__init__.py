"""Tool contracts and registry for the enterprise agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from bothesis.agent.models import AgentContext, ToolCall, ToolResult


class AgentTool(ABC):
    """An isolated, permission-aware capability available to the model."""

    name: str
    description: str
    parameters: dict[str, Any]

    @abstractmethod
    async def execute(self, arguments: dict[str, Any], ctx: AgentContext) -> ToolResult:
        """Execute the tool inside the authenticated request scope."""
        raise NotImplementedError

    def as_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """The agent's explicit allowlist of callable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        if not tool.name:
            raise ValueError("tool name must not be empty")
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.as_schema() for tool in self._tools.values()]

    def has(self, name: str) -> bool:
        return name in self._tools

    def arguments_are_valid(self, name: str, arguments: dict[str, Any]) -> bool:
        """Validate the small JSON-schema subset used by registered tools."""

        tool = self._tools.get(name)
        if tool is None:
            return False
        schema = tool.parameters
        properties = schema.get("properties")
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            return False
        if any(key not in arguments for key in required):
            return False
        if schema.get("additionalProperties") is False and any(
            key not in properties for key in arguments
        ):
            return False
        for key, value in arguments.items():
            property_schema = properties.get(key)
            if not isinstance(property_schema, dict):
                return False
            if not _matches_schema(value, property_schema):
                return False
        return True

    def public_label(self, name: str) -> str:
        """Return a stable user-facing activity label without call details."""

        if name == "knowledge_search":
            return "Search knowledge base"
        return name.replace("_", " ").replace("-", " ").strip().title() or "Run tool"

    async def execute(self, tc: ToolCall, ctx: AgentContext) -> ToolResult:
        tool = self._tools.get(tc.name)
        if tool is None:
            return ToolResult(
                call_id=tc.call_id,
                content="",
                error=f"Unknown tool: {tc.name}",
            )
        try:
            result = await tool.execute(tc.arguments, ctx)
        except Exception:
            # Tool errors are observations for the model, not stream failures.
            return ToolResult(
                call_id=tc.call_id,
                content="",
                error=f"Tool execution failed: {tc.name}",
            )
        if result.call_id not in ("", tc.call_id):
            return ToolResult(
                call_id=tc.call_id,
                content="",
                error=f"Tool returned an invalid call id: {tc.name}",
            )
        if result.call_id == tc.call_id:
            return result
        return ToolResult(
            call_id=tc.call_id,
            content=result.content,
            evidence=result.evidence,
            error=result.error,
            metadata=result.metadata,
        )


__all__ = ["AgentTool", "ToolRegistry"]


def _matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    expected_type = schema.get("type")
    if expected_type == "string":
        if not isinstance(value, str):
            return False
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        return not (
            isinstance(minimum, int) and len(value) < minimum
            or isinstance(maximum, int) and len(value) > maximum
        )
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return expected_type is None
