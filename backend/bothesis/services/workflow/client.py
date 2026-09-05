"""Reusable Temporal client connection provider."""

from __future__ import annotations

import asyncio

from temporalio.client import Client

from bothesis.services.workflow import TemporalSettings


class TemporalClientProvider:
    """Create one lazy Temporal client per application process."""

    def __init__(self, settings: TemporalSettings | None = None) -> None:
        self.settings = settings or TemporalSettings.from_environment()
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> Client:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                self._client = await Client.connect(
                    self.settings.target,
                    namespace=self.settings.namespace,
                    api_key=self.settings.api_key,
                    tls=self.settings.tls,
                )
        return self._client


__all__ = ["TemporalClientProvider"]
