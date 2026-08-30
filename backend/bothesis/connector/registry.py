"""Registry for provider-neutral connector implementations."""

from __future__ import annotations

from bothesis.connector import ConnectorDefinition


class ConnectorRegistry:
    """Register and resolve connector implementations by stable connector key."""

    def __init__(self, definitions: tuple[ConnectorDefinition, ...] = ()) -> None:
        self._definitions: dict[str, ConnectorDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ConnectorDefinition) -> None:
        key = definition.key.strip().casefold()
        if not key or len(key) > 64:
            raise ValueError("connector key is invalid")
        if key in self._definitions:
            raise ValueError(f"connector is already registered: {key}")
        self._definitions[key] = definition

    def get(self, connector_key: str) -> ConnectorDefinition:
        key = connector_key.strip().casefold()
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise LookupError(f"connector is not registered: {key}") from exc

    def list(self) -> tuple[ConnectorDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


__all__ = ["ConnectorRegistry"]
