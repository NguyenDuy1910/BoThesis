"""Canonical direct and effective access policy."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class AccessEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class AccessRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    effect: AccessEffect = AccessEffect.ALLOW
    principal: Principal
    permissions: list[str] = Field(default_factory=lambda: ["read"])


class DirectAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inherit: bool = True
    rules: list[AccessRule] = Field(default_factory=list)


class EffectiveAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reader_ids: list[str] = Field(default_factory=list)
    inherited_from: list[str] = Field(default_factory=list)

    @field_validator("reader_ids", "inherited_from")
    @classmethod
    def _normalise_ids(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in value if item.strip()})


class AccessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direct: DirectAccess = Field(default_factory=DirectAccess)
    effective: EffectiveAccess = Field(default_factory=EffectiveAccess)

    def to_reader_ids(self) -> list[str]:
        return list(self.effective.reader_ids)

    @property
    def is_public(self) -> bool:
        return "public" in self.effective.reader_ids

    @classmethod
    def from_reader_ids(
        cls,
        reader_ids: list[str] | set[str] | None = None,
        *,
        inherit: bool = True,
    ) -> "AccessPolicy":
        resolved = sorted({str(item).strip().lower() for item in (reader_ids or []) if str(item).strip()})
        rules = [
            AccessRule(principal=Principal(type=_principal_type(item), id=_principal_id(item)))
            for item in resolved
        ]
        return cls(
            direct=DirectAccess(inherit=inherit, rules=rules),
            effective=EffectiveAccess(reader_ids=resolved),
        )


def _principal_type(value: str) -> str:
    if value == "public":
        return "public"
    if ":" in value:
        return value.split(":", 1)[0]
    return "source"


def _principal_id(value: str) -> str:
    return value.split(":", 1)[1] if ":" in value else value
