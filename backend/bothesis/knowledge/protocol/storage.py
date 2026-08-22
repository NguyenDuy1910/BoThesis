"""Provider-neutral raw object references."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StorageProvider(str, Enum):
    S3 = "s3"
    POSTGRES = "postgres"
    LOCAL = "local"
    EXTERNAL = "external"


class StorageObject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: StorageProvider
    bucket: str | None = None
    key: str = Field(min_length=1)
    region: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    checksum: str | None = None
