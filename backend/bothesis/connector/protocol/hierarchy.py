"""Non-recursive hierarchy references for normalized items."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Hierarchy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_id: str | None = None
    root_id: str | None = None
    ancestor_ids: list[str] = Field(default_factory=list)
    depth: int = Field(default=0, ge=0)

    @field_validator("ancestor_ids")
    @classmethod
    def _normalise_ancestors(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]
