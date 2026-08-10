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
