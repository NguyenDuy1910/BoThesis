"""Retry-safe presigned uploads into mandatory object storage."""

from __future__ import annotations

import base64
import binascii
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.db.models import Item
from bothesis.services import (
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_UPLOAD_URL_SECONDS,
    AuthContext,
    ItemService,
    InvalidDocumentStateError,
    UploadConflictError,
    UploadStart,
    UploadTarget,
    UploadTooLargeError,
    UploadValidationError,
)
from bothesis.document_index.raw_storage import (
    DocumentStorage,
    ObjectStorageError,
    StoredObject,
)

log = logging.getLogger(__name__)


class UploadService:
    """Create Item metadata first, then upload original bytes to object storage."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        object_storage: DocumentStorage,
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
        upload_url_seconds: int = DEFAULT_UPLOAD_URL_SECONDS,
    ) -> None:
        if min(max_upload_bytes, upload_url_seconds) < 1:
            raise ValueError("upload limits must be greater than zero")
        self._session_factory = session_factory
        self._object_storage = object_storage
        self.max_upload_bytes = max_upload_bytes
        self._upload_url_seconds = upload_url_seconds

    async def start_upload(
        self,
        access: AuthContext,
        *,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        size_bytes: int,
    ) -> UploadStart:
        normalized_name = _file_name(file_name)
        normalized_type = _content_type(content_type)
        self._validate_upload_size(size_bytes)

        try:
            async with self._session_factory.begin() as session:
                if access.tenant_id is None:
                    raise UploadValidationError("an active tenant is required")
                item, _ = await ItemService(session).create_or_get_personal_upload(
                    access.user_id,
                    access.tenant_id,
                    idempotency_key=idempotency_key,
                    file_name=normalized_name,
                    mime_type=normalized_type,
                    size_bytes=size_bytes,
                    document_kind=_document_kind(normalized_type),
                )
        except InvalidDocumentStateError as exc:
            raise UploadConflictError(str(exc)) from exc

        assert item.upload is not None
        if item.upload.status == "available":
            return UploadStart(item=item, upload=item.upload, upload_required=False, target=None)
        if item.upload.status not in {"pending", "failed"}:
            raise UploadConflictError("item is not in an uploadable state")
        if not item.storage_key:
            raise UploadConflictError("item has no durable object storage key")
        request = self._object_storage.presign_upload(
            item.storage_key,
            content_type=normalized_type,
            expires_seconds=self._upload_url_seconds,
        )
        return UploadStart(
            item=item,
            upload=item.upload,
            upload_required=True,
            target=UploadTarget(mode="presigned", request=request),
        )

    async def complete_upload(
        self,
        access: AuthContext,
        document_id: UUID,
    ) -> Item:
        if access.tenant_id is None:
            raise UploadValidationError("an active tenant is required")
        async with self._session_factory() as session:
            item = await ItemService(session).get_owned_upload(
                document_id,
                access.user_id,
                access.tenant_id,
            )
            assert item.upload is not None
            if item.upload.status == "available":
                return item
            storage_key = item.storage_key
            expected_size = item.size_bytes
            expected_type = item.mime_type
        if not storage_key:
            raise ObjectStorageError("item has no object storage key")
        try:
            stored = await self._object_storage.head(storage_key)
            _validate_stored_object(
                stored,
                expected_size=expected_size,
                expected_content_type=expected_type,
            )
        except UploadValidationError:
            await self._record_failure(
                access,
                document_id,
                error_code="object_validation_failed",
            )
            raise
        except ObjectStorageError:
            await self._record_failure(
                access,
                document_id,
                error_code="object_validation_failed",
            )
            raise
        checksum = _checksum_hex(stored.checksum_sha256)
        async with self._session_factory.begin() as session:
            return await ItemService(session).mark_upload_available(
                document_id,
                access.user_id,
                access.tenant_id,
                content_sha256=checksum,
                storage_metadata={
                    "etag": stored.etag,
                    "version_id": stored.version_id,
                    "source_fingerprint": stored.source_fingerprint,
                },
            )

    async def get_document(
        self,
        access: AuthContext,
        document_id: UUID,
        *,
        include_hidden: bool = False,
    ) -> Item:
        if access.tenant_id is None:
            raise UploadValidationError("an active tenant is required")
        async with self._session_factory() as session:
            return await ItemService(session).get_owned_upload(
                document_id,
                access.user_id,
                access.tenant_id,
                include_deleted=include_hidden,
            )

    async def mark_failed(
        self,
        access: AuthContext,
        document_id: UUID,
        *,
        error_code: str,
    ) -> None:
        if access.tenant_id is None:
            return
        async with self._session_factory.begin() as session:
            await ItemService(session).mark_upload_failed(
                document_id,
                access.user_id,
                access.tenant_id,
                error_code=error_code,
            )

    async def _record_failure(
        self,
        access: AuthContext,
        document_id: UUID,
        *,
        error_code: str,
    ) -> None:
        try:
            await self.mark_failed(
                access,
                document_id,
                error_code=error_code,
            )
        except Exception:
            log.exception(
                "upload failure state could not be persisted document_id=%s",
                document_id,
            )

    def _validate_upload_size(self, size_bytes: int) -> None:
        if size_bytes < 1:
            raise UploadValidationError("upload size must be greater than zero")
        if size_bytes > self.max_upload_bytes:
            raise UploadTooLargeError(
                f"upload exceeds the {self.max_upload_bytes} byte limit"
            )

def _file_name(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 240
        or normalized in {".", ".."}
        or "\x00" in normalized
        or "/" in normalized
        or "\\" in normalized
    ):
        raise UploadValidationError("file name is invalid")
    return normalized


def _content_type(value: str) -> str:
    normalized = value.split(";", 1)[0].strip().casefold()
    if not normalized or len(normalized) > 255 or "/" not in normalized:
        raise UploadValidationError("content type is invalid")
    return normalized


def _validate_stored_object(
    stored: StoredObject,
    *,
    expected_size: int | None,
    expected_content_type: str | None,
) -> None:
    if expected_size is None or stored.size_bytes != expected_size:
        raise UploadValidationError(
            "uploaded object size does not match document metadata"
        )
    actual_type = _content_type(stored.content_type or "application/octet-stream")
    expected_type = _content_type(expected_content_type or "application/octet-stream")
    if (
        expected_type != "application/octet-stream"
        and actual_type != "application/octet-stream"
        and actual_type != expected_type
    ):
        raise UploadValidationError(
            "uploaded object content type does not match document metadata"
        )


def _checksum_hex(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if len(normalized) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in normalized
    ):
        return normalized.casefold()
    try:
        decoded = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError):
        return None
    return decoded.hex() if len(decoded) == 32 else None


__all__ = ["UploadService"]


def _document_kind(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type == "application/pdf":
        return "pdf"
    if content_type in {"text/html", "application/xhtml+xml"}:
        return "web_page"
    return "document"
