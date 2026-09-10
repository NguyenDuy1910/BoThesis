"""The finalized executable and model-visible tool surface for one step."""

from __future__ import annotations

from collections.abc import Iterable

from bothesis.agent.protocol import FunctionTool
from bothesis.agent.tools import ToolExposure
from bothesis.agent.tools.core.registry import ToolRegistry


class ToolRouter:
    """Resolve only tools exposed for the sampling request that created a call."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        allowed_names: Iterable[str] | None,
        sandbox_available: bool = True,
    ) -> None:
        self.registry = registry
        allowed = frozenset(allowed_names) if allowed_names is not None else None
        self._names = tuple(
            name
            for name, executor in registry.executors()
            if (allowed is None or name in allowed)
            and executor.exposure() is ToolExposure.DIRECT
            and (sandbox_available or not executor.spec().requires_sandbox)
        )

    @property
    def model_visible_specs(self) -> tuple[FunctionTool, ...]:
        return tuple(
            executor.as_function_tool()
            for name in self._names
            if (executor := self.registry.get(name)) is not None
        )

    def is_exposed(self, name: str) -> bool:
        return name in self._names


__all__ = ["ToolRouter"]
