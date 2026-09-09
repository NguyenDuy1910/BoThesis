"""Materialize a resource as native model content when its capability permits."""

from __future__ import annotations

from bothesis.agent.models import ToolResult
from bothesis.agent.tools import Tool, ToolInvocation, ToolSpec
from bothesis.observability import TraceSerializer


class MaterializeResource(Tool):
    """Make an available image visible to the next provider-neutral model step."""

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="materialize_resource",
            description=(
                "Make an available image visible as native model input on the next "
                "sampling step. Use it only when visual inspection is needed; it "
                "returns a confirmation and the image is added by the runtime."
            ),
            input_schema={
                "type": "object",
                "properties": {"resource_id": {"type": "string", "minLength": 1}},
                "required": ["resource_id"],
                "additionalProperties": False,
            },
            activity_label="View resource",
        )

    async def handle(self, invocation: ToolInvocation) -> ToolResult:
        resource_id = str(invocation.payload.arguments["resource_id"])
        resource = invocation.resource(resource_id)
        resolver = invocation.resource_resolver
        if resource is None:
            return ToolResult(content="", error="Resource is not available in this turn.", metadata={"outcome": "not_found", "result_count": 0})
        if resolver is None:
            return ToolResult(content="", error="Resource materialization is unavailable.", metadata={"outcome": "unavailable", "result_count": 0})
        # Trace start: materialize only the resource representation for this call.
        with invocation.session.tracer.span(
            "resource.materialize",
            attributes={"resolver": type(resolver).__name__},
            input=TraceSerializer.full(TraceSerializer.resource_input(resource)),
        ) as trace:
            content = await resolver.materialize(resource)
            trace.set_output(
                TraceSerializer.full(
                    TraceSerializer.resource_output(
                        action="materialize",
                        content_count=len(content),
                        representation=content,
                    )
                )
            )
            # Trace end: record the model-visible representation before closing.
        return ToolResult(
            content="Resource materialized for the next model step.",
            metadata={"outcome": "success", "result_count": 1},
            model_content=content,
        )


__all__ = ["MaterializeResource"]
