"""Canonical independently addressable source resources."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .access import AccessPolicy
from .content import AnyContentPart, TextPart
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
    original: StorageObject | None = None
    content: list[AnyContentPart] = Field(default_factory=list)

    def get_text_content(self) -> str:
        return "\n\n".join(part.text.strip() for part in self.content if isinstance(part, TextPart) and part.text.strip())


class FileItem(Item):
    type: Literal["file"] = "file"
    original: StorageObject


AnyItem = Annotated[
    CollectionItem | DocumentItem | FileItem,
    Field(discriminator="type"),
]
