"""S3-compatible raw document storage implemented with boto3."""

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
_AWS_S3_PROVIDER = "aws_s3"
_CLOUDFLARE_R2_PROVIDER = "cloudflare_r2"
_STORAGE_PROVIDERS = frozenset({_AWS_S3_PROVIDER, _CLOUDFLARE_R2_PROVIDER})


class S3DocumentStorage:
    """Store raw binaries in AWS S3 or Cloudflare R2 through boto3.

    Both providers expose the S3 API, so object operations and presigning stay
    in this one adapter. AWS S3 uses the standard boto3 credential chain. R2
    uses its account endpoint, path-style addressing, ``auto`` as its signing
    region, and an R2 API-token access-key pair. Passing ``client`` keeps the
    adapter independently testable.
    """

    def __init__(
        self,
        *,
        bucket: str,
        provider: str = _AWS_S3_PROVIDER,
        region: str | None = None,
        endpoint_url: str | None = None,
        addressing_style: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        timeout_seconds: float = 20,
        max_pool_connections: int = 20,
        client: Any | None = None,
    ) -> None:
        normalized_bucket = bucket.strip()
        if not normalized_bucket:
            raise ValueError("S3 bucket must not be blank")
        normalized_provider = _provider(provider)
        normalized_endpoint = _optional_string(endpoint_url)
        normalized_region = _optional_string(region)
        normalized_addressing_style = _addressing_style(
            addressing_style,
            provider=normalized_provider,
        )
        normalized_access_key_id, normalized_secret_access_key = _credentials(
            access_key_id,
            secret_access_key,
        )
        if normalized_provider == _CLOUDFLARE_R2_PROVIDER:
            if normalized_endpoint is None:
                raise ValueError("Cloudflare R2 requires an endpoint URL")
            if normalized_addressing_style != "path":
                raise ValueError("Cloudflare R2 requires path-style addressing")
            normalized_region = normalized_region or "auto"
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_pool_connections < 1:
            raise ValueError("max_pool_connections must be greater than zero")

        if client is None:
            try:
                session_arguments: dict[str, str | None] = {
                    "region_name": normalized_region,
                }
                if normalized_access_key_id is not None:
                    session_arguments["aws_access_key_id"] = normalized_access_key_id
                    session_arguments["aws_secret_access_key"] = (
                        normalized_secret_access_key
                    )
                session = boto3.Session(**session_arguments)
                client = session.client(
                    "s3",
                    endpoint_url=normalized_endpoint,
                    config=Config(
                        signature_version="s3v4",
                        connect_timeout=timeout_seconds,
                        read_timeout=timeout_seconds,
                        max_pool_connections=max_pool_connections,
                        retries={"mode": "standard", "max_attempts": 3},
                        s3={"addressing_style": normalized_addressing_style},
                    ),
                )
            except (BotoCoreError, ValueError) as exc:
                raise ObjectStorageError("S3-compatible client configuration failed") from exc

        self._bucket = normalized_bucket
        self._provider = normalized_provider
        self._client = client

    @classmethod
    def for_cloudflare_r2(
        cls,
        *,
        bucket: str,
        account_id: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        timeout_seconds: float = 20,
        max_pool_connections: int = 20,
        client: Any | None = None,
    ) -> S3DocumentStorage:
        """Build an R2 adapter with the S3-compatible settings R2 requires."""

        return cls(
            bucket=bucket,
            provider=_CLOUDFLARE_R2_PROVIDER,
            region="auto",
            endpoint_url=_r2_endpoint(account_id, endpoint_url),
            addressing_style="path",
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            timeout_seconds=timeout_seconds,
            max_pool_connections=max_pool_connections,
            client=client,
        )

    @property
    def bucket(self) -> str:
        """Return the configured bucket for source-lineage metadata."""

        return self._bucket

    @property
    def provider(self) -> str:
        """Return the concrete S3-compatible provider identifier."""

        return self._provider

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


def _provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in _STORAGE_PROVIDERS:
        supported = ", ".join(sorted(_STORAGE_PROVIDERS))
        raise ValueError(f"storage provider must be one of: {supported}")
    return normalized


def _addressing_style(value: str | None, *, provider: str) -> str:
    normalized = _optional_string(value)
    if normalized is None:
        return "path" if provider == _CLOUDFLARE_R2_PROVIDER else "auto"
    if normalized not in {"auto", "path", "virtual"}:
        raise ValueError("addressing_style must be auto, path, or virtual")
    return normalized


def _credentials(
    access_key_id: str | None,
    secret_access_key: str | None,
) -> tuple[str | None, str | None]:
    normalized_access_key_id = _optional_string(access_key_id)
    normalized_secret_access_key = _optional_string(secret_access_key)
    if (normalized_access_key_id is None) != (normalized_secret_access_key is None):
        raise ValueError(
            "access_key_id and secret_access_key must be configured together"
        )
    return normalized_access_key_id, normalized_secret_access_key


def _r2_endpoint(account_id: str | None, endpoint_url: str | None) -> str:
    normalized_endpoint = _optional_string(endpoint_url)
    if normalized_endpoint is not None:
        return normalized_endpoint
    normalized_account_id = _optional_string(account_id)
    if normalized_account_id is None:
        raise ValueError("Cloudflare R2 requires account_id or endpoint_url")
    return f"https://{normalized_account_id}.r2.cloudflarestorage.com"


__all__ = ["S3DocumentStorage"]
