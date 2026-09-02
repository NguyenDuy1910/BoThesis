"""BoThesis source adapters and validated ingestion hand-off contracts.

Each sub-package (confluence, jira, file, google_drive) implements the connector
contracts defined in ``connector.base`` and produces canonical items defined in
``bothesis.connector.protocol``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .base import BaseSourceConnector

ConnectorFactory = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    BaseSourceConnector,
]


@dataclass(frozen=True, slots=True)
class ConnectorDefinition:
    """Runtime connector registration; never persisted as tenant data."""

    key: str
    display_name: str
    authentication_type: str
    capabilities: tuple[str, ...]
    factory: ConnectorFactory

from .adapter import CheckpointedSourceConnectorAdapter
from .pipeline import ConnectorPipeline, ConnectorPipelineConfig
from bothesis.connector.protocol import AnyContentPart, AnyItem, ItemChange

__all__ = [
    "ConnectorPipeline",
    "ConnectorPipelineConfig",
    "ConnectorDefinition",
    "ConnectorFactory",
    "CheckpointedSourceConnectorAdapter",
    "AnyContentPart",
    "AnyItem",
    "ItemChange",
]
