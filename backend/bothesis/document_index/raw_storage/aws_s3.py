"""AWS S3 implementation of the raw document storage contract."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from . import (
    ObjectNotFoundError,
    ObjectStorageError,
    PresignedRequest,
    StoredObject,
)

_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class S3DocumentStorage:
    """Store raw binaries in S3 using the standard AWS credential chain.

    Configuration is explicit at construction time. When ``client`` is not
    supplied, boto3 resolves credentials from the standard AWS credential
    chain, including local profiles, environment variables, and workload
    roles. Passing a client keeps the adapter independently testable.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        addressing_style: str = "auto",
        timeout_seconds: float = 20,
        max_pool_connections: int = 20,
        client: Any | None = None,
    ) -> None:
        normalized_bucket = bucket.strip()
        if not normalized_bucket:
            raise ValueError("S3 bucket must not be blank")
        if addressing_style not in {"auto", "path", "virtual"}:
            raise ValueError("addressing_style must be auto, path, or virtual")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_pool_connections < 1:
            raise ValueError("max_pool_connections must be greater than zero")

        if client is None:
            try:
                session = boto3.Session(region_name=_optional_string(region))
                client = session.client(
                    "s3",
                    endpoint_url=_optional_string(endpoint_url),
                    config=Config(
                        signature_version="s3v4",
                        connect_timeout=timeout_seconds,
                        read_timeout=timeout_seconds,
                        max_pool_connections=max_pool_connections,
                        retries={"mode": "standard", "max_attempts": 3},
                        s3={"addressing_style": addressing_style},
                    ),
                )
            except (BotoCoreError, ValueError) as exc:
                raise ObjectStorageError("AWS S3 client configuration failed") from exc

        self._bucket = normalized_bucket
        self._client = client

    def presign_upload(
        self,
        key: str,
        *,
        content_type: str,
        expires_seconds: int,
    ) -> PresignedRequest:
        normalized_key = _object_key(key)
        expires_seconds = _expiry(expires_seconds)
        params = {
            "Bucket": self._bucket,
            "Key": normalized_key,
            "ContentType": content_type,
        }
        try:
            url = self._client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=expires_seconds,
                HttpMethod="PUT",
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError("S3 upload URL generation failed") from exc
        return PresignedRequest(
            url=url,
            method="PUT",
            headers={"Content-Type": content_type},
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_seconds),
        )

    def presign_download(
        self,
        key: str,
        *,
        expires_seconds: int,
    ) -> PresignedRequest:
        normalized_key = _object_key(key)
        expires_seconds = _expiry(expires_seconds)
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": normalized_key},
                ExpiresIn=expires_seconds,
                HttpMethod="GET",
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError("S3 download URL generation failed") from exc
        return PresignedRequest(
            url=url,
            method="GET",
            headers={},
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_seconds),
        )

    async def head(self, key: str) -> StoredObject:
        normalized_key = _object_key(key)
        try:
            result = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=normalized_key,
            )
        except ClientError as exc:
            _raise_client_error(exc, operation="inspect")
        except BotoCoreError as exc:
            raise ObjectStorageError("S3 object inspection failed") from exc
        return _stored_object(result)

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        normalized_key = _object_key(key)
        if max_bytes < 1:
            raise ValueError("max_bytes must be greater than zero")
        try:
            return await asyncio.to_thread(
                self._read_sync,
                normalized_key,
                max_bytes,
            )
        except ClientError as exc:
            _raise_client_error(exc, operation="read")
        except BotoCoreError as exc:
            raise ObjectStorageError("S3 object read failed") from exc

    def _read_sync(self, key: str, max_bytes: int) -> bytes:
        metadata = self._client.head_object(Bucket=self._bucket, Key=key)
        size_bytes = int(metadata.get("ContentLength", -1))
        if size_bytes < 0:
            raise ObjectStorageError("S3 did not return an object size")
        if size_bytes > max_bytes:
            raise ObjectStorageError(
                f"raw document exceeds the {max_bytes} byte read limit"
            )
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body = response["Body"]
        try:
            content = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(content) > max_bytes:
            raise ObjectStorageError(
                f"raw document exceeds the {max_bytes} byte read limit"
            )
        return bytes(content)

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)


def _stored_object(value: dict[str, Any]) -> StoredObject:
    try:
        size_bytes = int(value.get("ContentLength", -1))
    except (TypeError, ValueError) as exc:
        raise ObjectStorageError("S3 returned an invalid object size") from exc
    if size_bytes < 0:
        raise ObjectStorageError("S3 did not return an object size")
    return StoredObject(
        size_bytes=size_bytes,
        content_type=_optional_string(value.get("ContentType")),
        etag=_optional_string(value.get("ETag"), strip_quotes=True),
        version_id=_optional_string(value.get("VersionId")),
        checksum_sha256=_optional_string(value.get("ChecksumSHA256")),
    )


def _raise_client_error(exc: ClientError, *, operation: str) -> None:
    if _is_not_found(exc):
        raise ObjectNotFoundError("raw document object was not found") from exc
    raise ObjectStorageError(f"S3 object {operation} failed") from exc


def _is_not_found(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    return str(error.get("Code", "")) in _NOT_FOUND_CODES


def _object_key(value: str) -> str:
    normalized = value.strip().lstrip("/")
    if not normalized:
        raise ValueError("object storage key must not be blank")
    return normalized


def _expiry(value: int) -> int:
    if not 1 <= value <= 604_800:
        raise ValueError("presigned URL lifetime must be between 1 and 604800 seconds")
    return value


def _optional_string(value: object, *, strip_quotes: bool = False) -> str | None:
    normalized = str(value or "").strip()
    if strip_quotes:
        normalized = normalized.strip('"')
    return normalized or None


__all__ = ["S3DocumentStorage"]
