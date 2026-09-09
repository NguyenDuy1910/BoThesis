"""Long-lived in-memory runtime aggregate for one conversation session."""

from __future__ import annotations

from bothesis.agent import (
    ContextManager,
    SessionConfiguration,
    SessionServices,
    StepContext,
    TurnContext,
    ResourceResolver,
    ResourceRef,
)
from bothesis.agent.protocol import FunctionTool
from bothesis.agent.tools import ToolRegistry, ToolRouter
from bothesis.agent.transports import ResponseStream, response_stream
from bothesis.observability import NoopTracer, TraceSerializer, Tracer


class Session:
    """Coordinate configuration, dependencies and model-visible context."""

    def __init__(
        self,
        configuration: SessionConfiguration,
        services: SessionServices,
        context_manager: ContextManager,
    ) -> None:
        self.configuration = configuration
        self.services = services
        self.context_manager = context_manager
        self._tracer = services.tracer or NoopTracer()
        self._step_resources: dict[tuple[str, int], tuple[ResourceRef, ...]] = {}

    @property
    def model(self) -> ResponseStream:
        return response_stream(self.services.model)

    @property
    def tool_registry(self) -> ToolRegistry:
        registry = self.services.tool_registry
        if not isinstance(registry, ToolRegistry):
            raise TypeError("session tool_registry must be a ToolRegistry")
        return registry

    @property
    def resource_resolver(self) -> ResourceResolver | None:
        """The request-scoped resolver available to this agent run, if any."""

        return self.services.resource_resolver

    @property
    def tracer(self) -> Tracer:
        """The provider-neutral observability adapter for this session."""

        return self._tracer

    async def capture_step_context(self, turn: TurnContext) -> StepContext:
        """Capture the exact settings, environment and tool surface for one step."""

        await self.context_manager.start_turn(turn, self.resource_resolver)
        router = self._tool_router(turn)
        resources = self.context_manager.relevant_resources(turn)
        settings = turn.current_settings
        if settings.model is None:
            settings = settings.__class__(
                model=self.model.model,
                temperature=settings.temperature,
                max_output_tokens=settings.max_output_tokens,
                parallel_tool_calls=settings.parallel_tool_calls,
                provider_options=dict(settings.provider_options),
            )
        # Trace start: capture all runtime state considered for this snapshot.
        with self.tracer.span(
            "context.build",
            attributes={"step": turn.model_iteration, "tool_round": turn.tool_round},
            input=TraceSerializer.full(
                TraceSerializer.context_build_input(
                    turn,
                    previous_observations=turn.observations,
                    available_tools=router.model_visible_specs,
                )
            ),
        ) as trace:
            step_context = self.context_manager.capture_step_context(
                turn,
                settings=settings,
                tools=router.model_visible_specs,
                resources=resources,
            )
            self._step_resources[(step_context.turn_id, step_context.step_index)] = resources
            trace.set_output(
                TraceSerializer.full(
                    TraceSerializer.context_build_output(
                        step_context,
                        considered_input=turn.input_items,
                        observation_count=len(turn.observations),
                    )
                )
            )
            # Trace end: record the exact StepContext before returning it to the loop.
            return step_context

    def resources_for(self, step_context: StepContext) -> tuple[ResourceRef, ...]:
        """Return the resource scope selected for the immutable sampling step."""

        return self._step_resources.get(
            (step_context.turn_id, step_context.step_index), ()
        )

    def tool_router(self, step_context: StepContext) -> ToolRouter:
        """Recreate the execution router from the immutable exposed tool names."""

        return ToolRouter(
            self.tool_registry,
            allowed_names=tuple(
                tool.name
                for tool in step_context.tools
                if isinstance(tool, FunctionTool)
            ),
        )

    def _tool_router(self, turn: TurnContext) -> ToolRouter:
        context = turn.environment.agent_context
        tools_allowed = (
            turn.tool_round < self.configuration.max_tool_rounds
            and turn.tool_call_count < self.configuration.max_tool_calls
            and (
                context.allowed_tool_names is None
                or bool(context.allowed_tool_names)
            )
        )
        allowed_names = context.allowed_tool_names if tools_allowed else ()
        return ToolRouter(self.tool_registry, allowed_names=allowed_names)


__all__ = ["Session"]
