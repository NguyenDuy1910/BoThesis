"""Canonical independently addressable source resources."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .access import AccessPolicy
from .content import (
    AnyContentPart,
    CodePart,
    ImagePart,
    LinkPart,
    StructuredPart,
    TablePart,
    TextPart,
)
from .hierarchy import Hierarchy
from .source import SourceIdentity
from .storage import StorageObject


Metadata = dict[str, str | list[str]]


class CollectionKind(str, Enum):
    SPACE = "space"
    FOLDER = "folder"
    PROJECT = "project"
    CHANNEL = "channel"
    COLLECTION = "collection"
    DATABASE = "database"


class DocumentKind(str, Enum):
    PAGE = "page"
    PDF = "pdf"
    DOCUMENT = "document"
    IMAGE = "image"
    ISSUE = "issue"
    MESSAGE = "message"
    EMAIL = "email"
    NOTE = "note"
    WEB_PAGE = "web_page"
    RECORD = "record"


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: str
    title: str = Field(min_length=1)
    source: SourceIdentity
    hierarchy: Hierarchy = Field(default_factory=Hierarchy)
    access: AccessPolicy = Field(default_factory=AccessPolicy)
    metadata: Metadata = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def get_text_content(self) -> str:
        return ""


class CollectionItem(Item):
    type: Literal["collection"] = "collection"
    collection_kind: CollectionKind


class DocumentItem(Item):
    type: Literal["document"] = "document"
    document_kind: DocumentKind
    content: list[AnyContentPart] = Field(default_factory=list)
    original: StorageObject | None = None

    def get_text_content(self) -> str:
        return "\n\n".join(
            value
            for part in self.content
            if (value := _content_part_text(part))
        )


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


AnyItem = Annotated[
    CollectionItem | DocumentItem,
    Field(discriminator="type"),
]

def _content_part_text(part: AnyContentPart) -> str:
    if isinstance(part, TextPart):
        return part.text.strip()
    if isinstance(part, TablePart):
        rows = [part.columns, *part.rows] if part.columns else part.rows
        table = "\n".join(" | ".join(cell.strip() for cell in row) for row in rows)
        values = [value for value in (part.caption, table) if value and value.strip()]
        return "\n".join(value.strip() for value in values)
    if isinstance(part, ImagePart):
        values = (part.alt_text, part.ocr_text, part.description)
        return "\n".join(
            value.strip()
            for value in dict.fromkeys(values)
            if value and value.strip()
        )
    if isinstance(part, CodePart):
        return part.code.strip()
    if isinstance(part, StructuredPart):
        import json

        return json.dumps(
            part.data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(part, LinkPart):
        return f"{part.title.strip()}: {part.url}" if part.title and part.title.strip() else part.url
    return ""
