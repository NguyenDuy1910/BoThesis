"""Guest-only signal that a requested action needs a durable identity."""

from __future__ import annotations

from bothesis.agent.models import ToolResult
from bothesis.agent.tools import Tool, ToolInvocation, ToolSpec


class RequestIdentity(Tool):
    """Tell the client to upgrade a guest session before a governed action."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="request_identity",
            description=(
                "Use when a guest asks to save history permanently, upload a private "
                "file, enter a private workspace, create an agent, edit knowledge, "
                "or run any tool that changes external state. Do not use for public "
                "knowledge search, ordinary questions, or citation viewing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                    }
                },
                "required": ["reason"],
                "additionalProperties": False,
            },
            activity_label="Sign-in required",
        )

    async def handle(self, invocation: ToolInvocation) -> ToolResult:
        reason = str(invocation.payload.arguments.get("reason", "")).strip()
        return ToolResult(
            content="Sign in is required before this action can continue.",
            metadata={"outcome": "identity_required", "reason": reason},
        )


__all__ = ["RequestIdentity"]
