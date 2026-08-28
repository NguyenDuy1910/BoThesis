"""Incremental changes emitted by source adapters."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .items import AnyItem


class ChangeType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


class ItemChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ChangeType
    item_id: str = Field(min_length=1)
    item: AnyItem | None = None
    provider_version: str | None = Field(default=None, min_length=1)
    occurred_at: datetime | None = None
