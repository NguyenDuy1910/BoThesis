"""OpenRouter-native tool construction for the Responses API."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from bothesis.agent.execution import ExecutionCapability


class OpenRouterToolBuilder:
    """Append only policy-authorized OpenRouter server tools to one request."""

    def with_hosted_shell(
        self,
        tools: Sequence[dict[str, Any]],
        capability: ExecutionCapability | None,
    ) -> list[dict[str, Any]]:
        """Return declared tools plus OpenRouter's server-side shell when allowed."""

        rendered = list(tools)
        if capability is None or not capability.hosted_shell:
            return rendered
        if capability.provider != "openrouter":
            raise ValueError("hosted shell capability belongs to another provider")
        if any(tool.get("type") == "openrouter:shell" for tool in rendered):
            return rendered
        parameters: dict[str, Any] = {"engine": "openrouter"}
        if capability.environment_id is not None:
            parameters["environment"] = {
                "type": "container_reference",
                "container_id": capability.environment_id,
            }
        elif capability.workspace_file_ids:
            parameters["environment"] = {
                "type": "container_auto",
                "file_ids": list(capability.workspace_file_ids),
            }
        rendered.append({"type": "openrouter:shell", "parameters": parameters})
        return rendered


__all__ = ["OpenRouterToolBuilder"]
