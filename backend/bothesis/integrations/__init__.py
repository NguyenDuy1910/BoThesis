"""External integration contracts used at application service boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class SecretResolver(Protocol):
    """Resolve a secret reference without persisting secret values in PostgreSQL."""

    async def resolve(self, reference: str) -> Mapping[str, Any]: ...


from bothesis.integrations.secrets import EnvironmentSecretResolver  # noqa: E402

__all__ = ["EnvironmentSecretResolver", "SecretResolver"]
