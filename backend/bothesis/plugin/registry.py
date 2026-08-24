"""Runtime Plugin registry; definitions are deliberately not tenant rows."""

from __future__ import annotations

from bothesis.plugin import PluginDefinition


class PluginRegistry:
    """Register and resolve extension implementations by stable Plugin key."""

    def __init__(self, definitions: tuple[PluginDefinition, ...] = ()) -> None:
        self._definitions: dict[str, PluginDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: PluginDefinition) -> None:
        key = definition.key.strip().casefold()
        if not key or len(key) > 64:
            raise ValueError("plugin key is invalid")
        if key in self._definitions:
            raise ValueError(f"plugin is already registered: {key}")
        self._definitions[key] = definition

    def get(self, plugin_key: str) -> PluginDefinition:
        key = plugin_key.strip().casefold()
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise LookupError(f"plugin is not registered: {key}") from exc

    def list(self) -> tuple[PluginDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


__all__ = ["PluginRegistry"]
