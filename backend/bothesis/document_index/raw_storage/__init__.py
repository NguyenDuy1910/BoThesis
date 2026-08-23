"""Raw document storage contract and provider implementations.

Raw storage owns binary object access only. Document metadata, parsing, and
indexing remain outside this package.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable


class ObjectStorageError(RuntimeError):
    """Raised when raw object storage cannot complete an operation."""


class ObjectNotFoundError(ObjectStorageError):
    """Raised when an expected raw document object does not exist."""


@dataclass(frozen=True, slots=True)
class PresignedRequest:
    url: str
    method: str
    headers: Mapping[str, str]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StoredObject:
    size_bytes: int
    content_type: str | None
    etag: str | None = None
    version_id: str | None = None
    checksum_sha256: str | None = None

    @property
    def source_fingerprint(self) -> str:
        return (
            self.checksum_sha256 or self.version_id or self.etag or str(self.size_bytes)
        )


@runtime_checkable
class DocumentStorage(Protocol):
    """Replaceable raw-binary storage used by upload and processing flows."""

    def put_bytes(
        self,
        data: bytes,
        key: str,
        *,
        content_type: str | None = None,
    ) -> StoredObject: ...

    def put_path(
        self,
        path: Path,
        key: str,
        *,
        content_type: str | None = None,
    ) -> StoredObject: ...

    def presign_upload(
        self,
        key: str,
        *,
        content_type: str,
        expires_seconds: int,
    ) -> PresignedRequest: ...

    def presign_download(
        self,
        key: str,
        *,
        expires_seconds: int,
    ) -> PresignedRequest: ...

    async def head(self, key: str) -> StoredObject: ...

    async def read(self, key: str, *, max_bytes: int) -> bytes: ...

    async def download_to_path(
        self,
        key: str,
        path: Path,
        *,
        max_bytes: int,
    ) -> StoredObject: ...

    async def aclose(self) -> None: ...


from .aws_s3 import S3DocumentStorage  # noqa: E402
from .postgres import PostgresBlobStorage  # noqa: E402

__all__ = [
    "DocumentStorage",
    "ObjectNotFoundError",
    "ObjectStorageError",
    "PresignedRequest",
    "PostgresBlobStorage",
    "S3DocumentStorage",
    "StoredObject",
]
