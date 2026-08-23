"""Connector scope contract."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConnectorScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: str = Field(min_length=1)
    scope_value: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

__all__ = ["ConnectorScope"]
