"""Read resource content only when the agent explicitly requests it."""

from __future__ import annotations

from bothesis.agent.models import ToolResult
from bothesis.agent.tools import Tool, ToolInvocation, ToolSpec
from bothesis.observability import TraceSerializer


class ReadResource(Tool):
    """Resolve one current-turn resource into bounded, untrusted text."""

    def __init__(self, *, max_characters: int = 12_000) -> None:
        if max_characters < 1:
            raise ValueError("resource read limit must be greater than zero")
        self._max_characters = max_characters

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_resource",
            description=(
                "Read a bounded text representation of an available resource. Use it "
                "when the request requires that resource's contents. Returns untrusted "
                "text extracted from the resource."
            ),
            input_schema={
                "type": "object",
                "properties": {"resource_id": {"type": "string", "minLength": 1}},
                "required": ["resource_id"],
                "additionalProperties": False,
            },
            activity_label="Read resource",
        )

    async def handle(self, invocation: ToolInvocation) -> ToolResult:
        resource_id = str(invocation.payload.arguments["resource_id"])
        resource = invocation.resource(resource_id)
        resolver = invocation.resource_resolver
        if resource is None:
            return ToolResult(content="", error="Resource is not available in this turn.", metadata={"outcome": "not_found", "result_count": 0})
        if resolver is None:
            return ToolResult(content="", error="Resource reading is unavailable.", metadata={"outcome": "unavailable", "result_count": 0})
        # Trace start: resolve the referenced resource only for this tool call.
        with invocation.session.tracer.span(
            "resource.resolve",
            attributes={"resolver": type(resolver).__name__},
            input=TraceSerializer.full(TraceSerializer.resource_input(resource)),
        ) as trace:
            content = await resolver.read(resource, max_characters=self._max_characters)
            trace.set_output(
                TraceSerializer.full(
                    TraceSerializer.resource_output(
                        action="read",
                        content_count=len(content),
                        representation={"type": "text", "character_count": len(content)},
                    )
                )
            )
            # Trace end: record the safe resolved representation before closing.
        return ToolResult(
            content=content or "Resource contains no readable text.",
            metadata={"outcome": "success", "result_count": 1},
        )


__all__ = ["ReadResource"]
