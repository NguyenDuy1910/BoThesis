"""Retry-safe upload orchestration for uploader-owned Documents."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.db.models import Document
from bothesis.services import (
    DEFAULT_MAX_DATABASE_BLOB_BYTES,
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_UPLOAD_URL_SECONDS,
    AuthContext,
    DocumentService,
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
    PostgresBlobStorage,
    PresignedRequest,
    StoredObject,
)

log = logging.getLogger(__name__)


class UploadService:
    """Create metadata first, then place bytes in object storage or PostgreSQL."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        object_storage: DocumentStorage | None,
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
        max_database_blob_bytes: int = DEFAULT_MAX_DATABASE_BLOB_BYTES,
        upload_url_seconds: int = DEFAULT_UPLOAD_URL_SECONDS,
    ) -> None:
        if min(max_upload_bytes, max_database_blob_bytes, upload_url_seconds) < 1:
            raise ValueError("upload limits must be greater than zero")
        if max_database_blob_bytes > max_upload_bytes:
            raise ValueError("database blob limit must not exceed upload limit")
        self._session_factory = session_factory
        self._object_storage = object_storage
        self.max_upload_bytes = max_upload_bytes
        self.max_database_blob_bytes = max_database_blob_bytes
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
                document, _ = await DocumentService(
                    session
                ).create_or_get_personal_upload(
                    access.user_id,
                    idempotency_key=idempotency_key,
                    file_name=normalized_name,
                    mime_type=normalized_type,
                    size_bytes=size_bytes,
                    use_object_storage=self._object_storage is not None,
                )
        except InvalidDocumentStateError as exc:
            raise UploadConflictError(str(exc)) from exc

        if document.upload_status == "available":
            return UploadStart(document=document, upload_required=False, target=None)
        if document.upload_status not in {"pending", "failed"}:
            raise UploadConflictError("document is not in an uploadable state")

        if self._object_storage is not None and document.raw_storage_key:
            request = self._object_storage.presign_upload(
                document.raw_storage_key,
                content_type=normalized_type,
                expires_seconds=self._upload_url_seconds,
            )
            return UploadStart(
                document=document,
                upload_required=True,
                target=UploadTarget(mode="presigned", request=request),
            )

        self._validate_database_size(size_bytes)
        return UploadStart(
            document=document,
            upload_required=True,
            target=UploadTarget(
                mode="api",
                request=PresignedRequest(
                    url=f"/api/v1/documents/{document.id}/content",
                    method="PUT",
                    headers={"Content-Type": normalized_type},
                    expires_at=datetime.now(UTC)
                    + timedelta(seconds=self._upload_url_seconds),
                ),
            ),
        )

    async def store_fallback_content(
        self,
        access: AuthContext,
        document_id: UUID,
        content: bytes,
    ) -> Document:
        self._validate_database_size(len(content))
        original_object_key: str | None = None
        try:
            async with self._session_factory.begin() as session:
                documents = DocumentService(session)
                document = await documents.get_owned_upload(
                    document_id,
                    access.user_id,
                    for_update=True,
                )
                if document.upload_status == "available":
                    return document
                if len(content) != document.size_bytes:
                    raise UploadValidationError(
                        "uploaded content size does not match document metadata"
                    )
                original_object_key = document.raw_storage_key
                digest = hashlib.sha256(content).hexdigest()
                await PostgresBlobStorage(session).write(document.id, content)
                storage_metadata = {
                    "backend": "postgresql",
                    "source_fingerprint": digest,
                }
                if original_object_key:
                    storage_metadata["retained_object_key"] = original_object_key
                document = await documents.mark_upload_available(
                    document.id,
                    access.user_id,
                    raw_storage_key=None,
                    content_sha256=digest,
                    storage_metadata=storage_metadata,
                )
        except UploadValidationError:
            await self._record_failure(
                access,
                document_id,
                error_code="database_blob_validation_failed",
            )
            raise

        return document

    async def complete_upload(
        self,
        access: AuthContext,
        document_id: UUID,
    ) -> Document:
        async with self._session_factory() as session:
            document = await DocumentService(session).get_owned_upload(
                document_id,
                access.user_id,
            )
            if document.upload_status == "available":
                return document
            raw_storage_key = document.raw_storage_key
            expected_size = document.size_bytes
            expected_type = document.mime_type

        if not raw_storage_key:
            async with self._session_factory.begin() as session:
                documents = DocumentService(session)
                raw_bytes = await PostgresBlobStorage(session).read(document_id)
                if len(raw_bytes) != expected_size:
                    raise UploadValidationError(
                        "stored content size does not match document metadata"
                    )
                return await documents.mark_upload_available(
                    document_id,
                    access.user_id,
                    raw_storage_key=None,
                    content_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    storage_metadata={
                        "backend": "postgresql",
                        "source_fingerprint": hashlib.sha256(raw_bytes).hexdigest(),
                    },
                )

        if self._object_storage is None:
            raise ObjectStorageError("object storage is not configured")
        try:
            stored = await self._object_storage.head(raw_storage_key)
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
            return await DocumentService(session).mark_upload_available(
                document_id,
                access.user_id,
                raw_storage_key=raw_storage_key,
                content_sha256=checksum,
                storage_metadata={
                    "backend": "object",
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
    ) -> Document:
        async with self._session_factory() as session:
            return await DocumentService(session).get_owned_upload(
                document_id,
                access.user_id,
                include_hidden=include_hidden,
            )

    async def mark_failed(
        self,
        access: AuthContext,
        document_id: UUID,
        *,
        error_code: str,
    ) -> None:
        async with self._session_factory.begin() as session:
            await DocumentService(session).mark_upload_failed(
                document_id,
                access.user_id,
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

    def _validate_database_size(self, size_bytes: int) -> None:
        if size_bytes > self.max_database_blob_bytes:
            raise UploadTooLargeError(
                "object storage is unavailable and the file exceeds the "
                f"{self.max_database_blob_bytes} byte database fallback limit"
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
