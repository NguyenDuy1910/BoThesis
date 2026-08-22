"""Content contained by a document item, never another top-level item."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BoundingBox(BaseModel):
    """A visual rectangle in the coordinate system of a rendered element."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _stay_inside_normalized_page(self) -> "BoundingBox":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("bounding box must remain inside normalized coordinates")
        return self


class ContentPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # A parser may provide a native stable ID.  Chunking supplies a
    # deterministic document-local fallback when it does not.
    element_id: str | None = Field(default=None, min_length=1)
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    section_path: tuple[str, ...] = ()
    anchor: str | None = None
    bounding_box: BoundingBox | None = None


class TextPart(ContentPart):
    type: Literal["text"] = "text"
    text: str
    link: str | None = None


class ImagePart(ContentPart):
    type: Literal["image"] = "image"
    url: str | None = None
    storage: str | None = None
    alt_text: str | None = None
    ocr_text: str | None = None
    description: str | None = None


class TablePart(ContentPart):
    type: Literal["table"] = "table"
    rows: list[list[str]] = Field(default_factory=list)
    caption: str | None = None


class StructuredPart(ContentPart):
    type: Literal["structured"] = "structured"
    data: dict[str, Any] = Field(default_factory=dict)


class LinkPart(ContentPart):
    type: Literal["link"] = "link"
    url: str = Field(min_length=1)
    title: str | None = None


class CodePart(ContentPart):
    type: Literal["code"] = "code"
    code: str
    language: str | None = None


AnyContentPart = Annotated[
    TextPart | ImagePart | TablePart | StructuredPart | LinkPart | CodePart,
    Field(discriminator="type"),
]


__all__ = [
    "AnyContentPart",
    "BoundingBox",
    "CodePart",
    "ContentPart",
    "ImagePart",
    "LinkPart",
    "StructuredPart",
    "TablePart",
    "TextPart",
]
