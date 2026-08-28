"""Provider-neutral extension contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from bothesis.connector.base import BaseSourceConnector

PluginFactory = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    BaseSourceConnector,
]


@dataclass(frozen=True, slots=True)
class PluginDefinition:
    key: str
    display_name: str
    authentication_type: str
    capabilities: tuple[str, ...]
    factory: PluginFactory


__all__ = ["PluginDefinition", "PluginFactory"]
