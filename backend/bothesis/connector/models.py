"""Small connector orchestration contracts.

Source resources and retrieval payloads are owned by
``bothesis.knowledge.protocol`` and ``bothesis.connector.qdrant``. This
module only contains connector runtime state and operational failure records.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConnectorCheckpoint(BaseModel):
    """Base checkpoint persisted between incremental connector runs."""

    model_config = ConfigDict(extra="forbid")


class SourceCheckpoint(ConnectorCheckpoint):
    """Cursor for APIs ordered by modification time and external ID."""

    updated_at: str | None = None
    cursor: str | None = None


class ConnectorScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: str = Field(min_length=1)
    scope_value: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SlimItem(BaseModel):
    """Minimal item reference used by permission synchronisation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    permission_data: dict[str, Any] | None = None


class ItemFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1)
    item_url: str | None = None


class ConnectorFailure(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    failed_item: ItemFailure | None = None
    failure_message: str = Field(min_length=1)
    exception: Exception | None = None


__all__ = [
    "ConnectorCheckpoint",
    "ConnectorFailure",
    "ConnectorScope",
    "ItemFailure",
    "SlimItem",
    "SourceCheckpoint",
]
