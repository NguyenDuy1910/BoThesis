"""OpenRouter hosted-execution capability metadata."""

from __future__ import annotations

from bothesis.agent.execution import ExecutionCapability


class OpenRouterExecutionCapabilityResolver:
    """Expose OpenRouter's hosted features through a provider-neutral contract."""

    def resolve(
        self, *, provider: str, model: str | None
    ) -> ExecutionCapability:
        available = provider == "openrouter" and bool(model)
        return ExecutionCapability(
            provider=provider,
            model=model,
            hosted_shell=available,
            provider_files=available,
            persistent_environments=available,
        )


__all__ = ["OpenRouterExecutionCapabilityResolver"]
