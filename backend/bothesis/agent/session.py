"""Long-lived in-memory runtime aggregate for one conversation session."""

from __future__ import annotations

from bothesis.agent import (
    ContextManager,
    ResolvedStepSettings,
    SessionConfiguration,
    SessionServices,
    StepContext,
    TurnContext,
    TurnEnvironmentSnapshot,
)
from bothesis.agent.tools import ToolRegistry, ToolRouter
from bothesis.agent.transports import ResponseStream, response_stream


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

    @property
    def model(self) -> ResponseStream:
        return response_stream(self.services.model)

    @property
    def tool_registry(self) -> ToolRegistry:
        registry = self.services.tool_registry
        if not isinstance(registry, ToolRegistry):
            raise TypeError("session tool_registry must be a ToolRegistry")
        return registry

    async def capture_step_context(self, turn: TurnContext) -> StepContext:
        """Capture the exact settings, environment and tool surface for one step."""

        configuration = self.configuration
        tools_allowed = (
            turn.tool_round < configuration.max_tool_rounds
            and turn.tool_call_count < configuration.max_tool_calls
            and (
                turn.environment.agent_context.allowed_tool_names is None
                or bool(turn.environment.agent_context.allowed_tool_names)
            )
        )
        allowed_names = (
            turn.environment.agent_context.allowed_tool_names if tools_allowed else ()
        )
        settings = ResolvedStepSettings(
            model=turn.current_settings.model or self.model.model,
            temperature=turn.current_settings.temperature,
            max_output_tokens=turn.current_settings.max_output_tokens,
            parallel_tool_calls=turn.current_settings.parallel_tool_calls,
            provider_options=dict(turn.current_settings.provider_options),
        )
        environment = TurnEnvironmentSnapshot(agent_context=turn.environment.agent_context)
        return StepContext(
            turn=turn,
            settings=settings,
            environment=environment,
            tool_router=ToolRouter(self.tool_registry, allowed_names=allowed_names),
        )


__all__ = ["Session"]
