"""Resolution of connection providers by provider key or connector key."""

from __future__ import annotations

from collections.abc import Iterable

from bothesis.integrations import ConnectionProvider


class ConnectionProviderRegistry:
    """Hold the providers this deployment configured and resolve them.

    A connector key resolves to at most one provider: Confluence is reached
    through Atlassian and nothing else. Connectors with no provider — managed
    file uploads, or a Confluence site configured with an API token rather than
    an authorization — resolve to ``None``, which is a supported answer rather
    than an error.
    """

    def __init__(self, providers: Iterable[ConnectionProvider] = ()) -> None:
        self._by_provider_key: dict[str, ConnectionProvider] = {}
        self._by_connector_key: dict[str, ConnectionProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ConnectionProvider) -> None:
        definition = provider.definition
        key = definition.key.strip().casefold()
        if not key:
            raise ValueError("provider key is invalid")
        if key in self._by_provider_key:
            raise ValueError(f"provider is already registered: {key}")
        self._by_provider_key[key] = provider
        for capability in definition.capabilities:
            connector_key = capability.connector_key.strip().casefold()
            if connector_key in self._by_connector_key:
                raise ValueError(
                    f"connector is already provided by another provider: {connector_key}"
                )
            self._by_connector_key[connector_key] = provider

    def get(self, provider_key: str) -> ConnectionProvider:
        try:
            return self._by_provider_key[provider_key.strip().casefold()]
        except KeyError as exc:
            raise LookupError(f"provider is not registered: {provider_key}") from exc

    def for_connector(self, connector_key: str) -> ConnectionProvider | None:
        return self._by_connector_key.get(connector_key.strip().casefold())

    def list(self) -> tuple[ConnectionProvider, ...]:
        return tuple(
            self._by_provider_key[key] for key in sorted(self._by_provider_key)
        )


__all__ = ["ConnectionProviderRegistry"]
