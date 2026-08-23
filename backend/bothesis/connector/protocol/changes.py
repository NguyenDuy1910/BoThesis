"""Incremental changes emitted by source adapters."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .items import AnyItem


class ChangeType(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"
    MOVE = "move"
    ACCESS_CHANGED = "access_changed"


class ItemChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ChangeType
    item_id: str = Field(min_length=1)
    item: AnyItem | None = None
    occurred_at: datetime | None = None
