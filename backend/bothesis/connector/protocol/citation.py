"""Stable source provenance contracts owned by the connector boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BoundingBox(BaseModel):
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


class CitationSpan(BaseModel):
    """One immutable, element-local provenance range."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int | None = Field(default=None, ge=1)
    element_id: str | None = Field(default=None, min_length=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    bounding_box: BoundingBox | None = None

    @model_validator(mode="after")
    def _validate_offsets(self) -> "CitationSpan":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be supplied together")
        if self.start_offset is not None and self.end_offset is not None and self.end_offset < self.start_offset:
            raise ValueError("end_offset must not precede start_offset")
        return self


class CitationInfo(BaseModel):
    """A source-independent location made from one or more provenance spans."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    section: str | None = None
    section_path: tuple[str, ...] = ()
    anchor: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    spans: tuple[CitationSpan, ...] = ()

    @model_validator(mode="after")
    def _validate_page_range(self) -> "CitationInfo":
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must not precede page_start")
        return self


__all__ = ["BoundingBox", "CitationInfo", "CitationSpan"]
