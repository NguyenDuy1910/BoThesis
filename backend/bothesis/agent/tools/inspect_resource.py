"""Inspect metadata for one resource available to the current agent turn."""

from __future__ import annotations

import json

from bothesis.agent.models import ToolResult
from bothesis.agent.tools import Tool, ToolInvocation, ToolSpec
from bothesis.observability import TraceSerializer


class InspectResource(Tool):
    """Expose safe resource metadata without reading or parsing its content."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="inspect_resource",
            description=(
                "Inspect an available resource's safe metadata without reading its "
                "contents. Use it to identify a resource or decide whether a content "
                "read is needed. Returns metadata only."
            ),
            input_schema={
                "type": "object",
                "properties": {"resource_id": {"type": "string", "minLength": 1}},
                "required": ["resource_id"],
                "additionalProperties": False,
            },
        )

    async def handle(self, invocation: ToolInvocation) -> ToolResult:
        resource_id = str(invocation.payload.arguments["resource_id"])
        resource = invocation.resource(resource_id)
        resolver = invocation.resource_resolver
        if resource is None:
            return ToolResult(content="", error="Resource is not available in this turn.", metadata={"outcome": "not_found", "result_count": 0})
        if resolver is None:
            return ToolResult(content="", error="Resource inspection is unavailable.", metadata={"outcome": "unavailable", "result_count": 0})
        # Trace start: inspect resource metadata within the originating tool call.
        with invocation.session.tracer.span(
            "resource.inspect",
            attributes={"resolver": type(resolver).__name__},
            input=TraceSerializer.full(TraceSerializer.resource_input(resource)),
        ) as trace:
            details = await resolver.inspect(resource)
            trace.set_output(
                TraceSerializer.full(
                    TraceSerializer.resource_output(
                        action="inspect",
                        content_count=len(details),
                        representation=details,
                    )
                )
            )
            # Trace end: the inspected representation is recorded before closing.
        return ToolResult(
            content=json.dumps(details, ensure_ascii=False, sort_keys=True),
            metadata={"outcome": "success", "result_count": 1},
        )


__all__ = ["InspectResource"]
