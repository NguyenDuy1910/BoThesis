"""The explicit allowlist of tools available to one conversation runtime."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from bothesis.agent.protocol import FunctionTool
from bothesis.agent.tools import Tool, ToolDefinition


class ToolRegistry:
    """Register tools, expose model definitions, and resolve invocations."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        definition = tool.definition
        name = definition.name.strip()
        if not name:
            raise ValueError("tool name must not be empty")
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    def function_tools(self) -> tuple[FunctionTool, ...]:
        """Adapt core definitions to the provider-neutral wire contract."""

        return tuple(
            tool.as_function_tool() for tool in self._tools.values()
        )

    def arguments_are_valid(self, name: str, arguments: Mapping[str, Any]) -> bool:
        tool = self.get(name)
        return tool is not None and _matches_schema(arguments, tool.definition.input_schema)

    def is_tool_arguments_payload(self, text: str) -> bool:
        """Whether a model text response is a schema-valid tool payload.

        A provider can occasionally serialize a function-call payload as plain
        message text. Such text is an internal command, never a user answer.
        """

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, Mapping):
            return False
        return any(
            _matches_schema(payload, tool.definition.input_schema)
            for tool in self._tools.values()
        )

def _matches_schema(value: object, schema: Mapping[str, Any]) -> bool:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, Mapping):
            return False
        properties = schema.get("properties")
        required = schema.get("required", ())
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            return False
        if any(not isinstance(key, str) or key not in value for key in required):
            return False
        if schema.get("additionalProperties") is False and any(
            key not in properties for key in value
        ):
            return False
        return all(
            isinstance(key, str)
            and isinstance(properties.get(key), Mapping)
            and _matches_schema(item, properties[key])
            for key, item in value.items()
        )
    if expected_type == "array":
        if not isinstance(value, list):
            return False
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        items = schema.get("items")
        return not isinstance(items, Mapping) or all(
            _matches_schema(item, items) for item in value
        )
    if expected_type == "string":
        if not isinstance(value, str):
            return False
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        return not (
            isinstance(minimum, int)
            and len(value) < minimum
            or isinstance(maximum, int)
            and len(value) > maximum
        )
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return expected_type is None


__all__ = ["ToolRegistry"]
