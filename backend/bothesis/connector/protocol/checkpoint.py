"""Checkpoint contracts owned by source synchronization."""

from pydantic import BaseModel, ConfigDict, Field


class ConnectorCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCheckpoint(ConnectorCheckpoint):
    updated_at: str | None = None
    cursor: str | None = None
    versions: dict[str, str] = Field(default_factory=dict)

__all__ = ["ConnectorCheckpoint", "SourceCheckpoint"]
