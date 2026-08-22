"""Connector-only contracts: checkpoints, scopes, and incremental sync."""

from .checkpoint import ConnectorCheckpoint, SourceCheckpoint
from .scope import ConnectorScope
from bothesis.knowledge.protocol import ChangeType, ItemChange

__all__ = ["ChangeType", "ConnectorCheckpoint", "ConnectorScope", "ItemChange", "SourceCheckpoint"]
