"""Provider-neutral source identity."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SourceProvider(str, Enum):
    SLACK = "slack"
    CONFLUENCE = "confluence"
    FILE = "file"
    GOOGLE_DRIVE = "google_drive"
    JIRA = "jira"
    NOTION = "notion"


class SourceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    connector_id: str = Field(min_length=1)
    provider: SourceProvider
    external_id: str = Field(min_length=1)
    external_version: str | None = None
    etag: str | None = None
    url: str | None = None
