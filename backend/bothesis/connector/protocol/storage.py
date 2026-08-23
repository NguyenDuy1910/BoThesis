"""Canonical raw-object references and the connector storage boundary."""

from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from typing import Protocol, runtime_checkable


class StorageObject(BaseModel):
    """Durable reference to an original source object.

    The reference deliberately contains no access URL.  Callers resolve a
    short-lived URL from ``provider``/``bucket``/``key`` when an authorized
    user asks to view the original object.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    provider: str | None = Field(default=None, min_length=1)
    bucket: str | None = Field(default=None, min_length=1)
    region: str | None = Field(default=None, min_length=1)
    file_name: str | None = Field(default=None, min_length=1)
    size_bytes: int | None = Field(default=None, ge=0)
    content_type: str | None = Field(default=None, min_length=1)
    checksum_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    etag: str | None = Field(default=None, min_length=1)
    version_id: str | None = Field(default=None, min_length=1)


@runtime_checkable
class RawObjectStore(Protocol):
    def put_bytes(self, data: bytes, key: str, *, content_type: str | None = None) -> object: ...

    def put_path(self, path: Path, key: str, *, content_type: str | None = None) -> object: ...


__all__ = ["RawObjectStore", "StorageObject"]
