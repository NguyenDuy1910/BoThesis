"""Checkpoint contracts owned by source synchronization."""

from pydantic import BaseModel, ConfigDict


class ConnectorCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCheckpoint(ConnectorCheckpoint):
    updated_at: str | None = None
    cursor: str | None = None

__all__ = ["ConnectorCheckpoint", "SourceCheckpoint"]
