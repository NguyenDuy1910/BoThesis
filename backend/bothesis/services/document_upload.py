"""Retry-safe presigned uploads into mandatory object storage."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.connector.file import FinxFileExtensions
from bothesis.db.models import Item
from bothesis.storage import (
    DocumentStorage,
    ObjectStorageError,
    StoredObject,
)
from bothesis.services.identity_access.authorization import AuthorizationService
from bothesis.services.item import ItemService
from bothesis.services.item_ingestion import ItemIngestionService
from bothesis.services.workflow import NativeUploadIndexingInput
from bothesis.services.workflow.service import TemporalWorkflowService
from bothesis.services import (
    COLLECTION_READ_PERMISSION,
    COLLECTION_UPDATE_PERMISSION,
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_UPLOAD_URL_SECONDS,
    AsyncUploadStream,
    AuthContext,
    AuthorizationError,
    StoredFileContent,
    CollectionUpload,
    DocumentNotFoundError,
    DocumentProcessingError,
    InvalidDocumentStateError,
    UploadConflictError,
    UploadStart,
    UploadTarget,
    UploadTooLargeError,
    UploadValidationError,
    require_user_identity,
)
log = logging.getLogger(__name__)


class DocumentUploadService:
    """Create Item metadata first, then upload original bytes to object storage."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        object_storage: DocumentStorage,
        ingestion_service: ItemIngestionService,
        document_source: StoredFileContent,
        workflows: TemporalWorkflowService,
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
        upload_url_seconds: int = DEFAULT_UPLOAD_URL_SECONDS,
    ) -> None:
        if min(max_upload_bytes, upload_url_seconds) < 1:
            raise ValueError("upload limits must be greater than zero")
        self._session_factory = session_factory
        self._object_storage = object_storage
        self._ingestion = ingestion_service
        self._document_source = document_source
        self._workflows = workflows
        self.max_upload_bytes = max_upload_bytes
        self._upload_url_seconds = upload_url_seconds

    async def start_upload(
        self,
        access: AuthContext,
        *,
        collection_id: UUID,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        size_bytes: int,
        purpose: str = "knowledge",
    ) -> UploadStart:
        if access.is_guest:
            raise AuthorizationError("sign in is required for private uploads")
        if purpose not in {"knowledge", "conversation_attachment"}:
            raise UploadValidationError("unsupported document purpose")
        user_id = require_user_identity(access)
        normalized_name = _file_name(file_name)
        normalized_type = _content_type(content_type)
        self._validate_upload_size(size_bytes)

        try:
            async with self._session_factory.begin() as session:
                if access.tenant_id is None:
                    raise UploadValidationError("an active tenant is required")
                await self._require_writable_collection(access, collection_id, session=session)
                item, created = await ItemService(session).create_or_get_collection_upload(
                    user_id, access.tenant_id, collection_id,
                    idempotency_key=idempotency_key, file_name=normalized_name,
                    mime_type=normalized_type, size_bytes=size_bytes,
                    document_type=_document_type(normalized_type),
                    metadata={"purpose": purpose},
                )
        except InvalidDocumentStateError as exc:
            raise UploadConflictError(str(exc)) from exc

        assert item.upload is not None
        if item.upload.status == "available":
            if purpose == "knowledge":
                await self._queue_indexing(item)
            return UploadStart(
                item=item, upload=item.upload, upload_required=False, target=None, created=created
            )
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
            created=created,
        )

    async def upload_to_collection(
        self,
        access: AuthContext,
        collection_id: UUID,
        *,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        content: AsyncUploadStream,
        purpose: str = "knowledge",
    ) -> CollectionUpload:
        """Store one native file and queue its independent semantic indexing."""

        if access.is_guest:
            raise AuthorizationError("sign in is required for private uploads")
        if purpose not in {"knowledge", "conversation_attachment"}:
            raise UploadValidationError("unsupported document purpose")
        if access.tenant_id is None:
            raise UploadValidationError("an active tenant is required")
        user_id = require_user_identity(access)
        normalized_name = _file_name(file_name)
        normalized_type = _content_type(content_type)
        _validate_supported_file(normalized_name)
        await self._require_writable_collection(access, collection_id)
        temporary_path, size_bytes = await self._spool(content, normalized_name)
        try:
            try:
                async with self._session_factory.begin() as session:
                    await self._require_writable_collection(
                        access, collection_id, session=session
                    )
                    item, created = await ItemService(
                        session
                    ).create_or_get_collection_upload(
                        user_id,
                        access.tenant_id,
                        collection_id,
                        idempotency_key=idempotency_key,
                        file_name=normalized_name,
                        mime_type=normalized_type,
                        size_bytes=size_bytes,
                        document_type=_document_type(normalized_type),
                        metadata={"purpose": purpose},
                    )
            except InvalidDocumentStateError as exc:
                raise UploadConflictError(str(exc)) from exc

            assert item.upload is not None
            if item.upload.status != "available":
                if not item.storage_key:
                    raise UploadConflictError("item has no durable object storage key")
                try:
                    stored = await asyncio.to_thread(
                        self._object_storage.put_path,
                        temporary_path,
                        item.storage_key,
                        content_type=normalized_type,
                    )
                    _validate_stored_object(
                        stored,
                        expected_size=size_bytes,
                        expected_content_type=normalized_type,
                    )
                except UploadValidationError:
                    await self._record_failure(
                        access, item.id, error_code="object_validation_failed"
                    )
                    raise
                except ObjectStorageError:
                    await self._record_failure(
                        access, item.id, error_code="object_storage_failed"
                    )
                    raise
                except Exception as exc:
                    await self._record_failure(
                        access, item.id, error_code="object_storage_failed"
                    )
                    raise ObjectStorageError("object storage upload failed") from exc
                async with self._session_factory.begin() as session:
                    item = await ItemService(session).mark_upload_available(
                        item.id,
                        user_id,
                        access.tenant_id,
                        storage_metadata={
                            "etag": stored.etag,
                            "version_id": stored.version_id,
                        },
                    )
            if purpose == "knowledge" and item.index_status != "ready":
                await self._queue_indexing(item)
            return CollectionUpload(item=item, created=created)
        finally:
            temporary_path.unlink(missing_ok=True)

    async def complete_upload(
        self,
        access: AuthContext,
        document_id: UUID,
    ) -> Item:
        if access.is_guest:
            raise AuthorizationError("sign in is required for private uploads")
        if access.tenant_id is None:
            raise UploadValidationError("an active tenant is required")
        async with self._session_factory() as session:
            item = await ItemService(session).get_upload_for_access(
                document_id, access, permission=COLLECTION_UPDATE_PERMISSION
            )
            assert item.upload is not None
            if item.upload.status == "available":
                if (item.metadata_ or {}).get("purpose", "knowledge") == "knowledge":
                    await self._queue_indexing(item)
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
        async with self._session_factory.begin() as session:
            item = await ItemService(session).mark_upload_available(
                document_id,
                item.upload.owner_user_id,
                access.tenant_id,
                storage_metadata={
                    "etag": stored.etag,
                    "version_id": stored.version_id,
                },
            )
        if (item.metadata_ or {}).get("purpose", "knowledge") == "knowledge":
            await self._queue_indexing(item)
        return item

    async def retry_indexing(
        self,
        access: AuthContext,
        document_id: UUID,
    ) -> Item:
        if access.is_guest:
            raise AuthorizationError("sign in is required for private uploads")
        require_user_identity(access)
        document = await self.get_document(
            access,
            document_id,
            permission=COLLECTION_UPDATE_PERMISSION,
        )
        if document.upload is None or document.upload.status != "available":
            raise UploadConflictError(
                "the original file is unavailable; upload the file again"
            )
        return await self._index_available(document, access=access)

    async def delete_document(
        self,
        access: AuthContext,
        document_id: UUID,
    ) -> None:
        if access.is_guest:
            raise AuthorizationError("sign in is required to remove documents")
        require_user_identity(access)
        await self._ingestion.remove_upload(document_id, access=access)

    async def get_document(
        self,
        access: AuthContext,
        document_id: UUID,
        *,
        permission: str = COLLECTION_READ_PERMISSION,
    ) -> Item:
        if access.tenant_id is None:
            raise UploadValidationError("an active tenant is required")
        async with self._session_factory() as session:
            return await ItemService(session).get_upload_for_access(
                document_id,
                access,
                permission=permission,
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
        user_id = require_user_identity(access)
        async with self._session_factory.begin() as session:
            await ItemService(session).mark_upload_failed(
                document_id,
                user_id,
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

    async def _index_available(
        self,
        document: Item,
        *,
        access: AuthContext,
    ) -> Item:
        try:
            return await self._ingestion.index_upload(
                document.id,
                access=access,
                source=self._document_source,
            )
        except DocumentProcessingError:
            return await self.get_document(access, document.id)

    async def _queue_indexing(self, document: Item) -> None:
        """Best-effort dispatch after durable bytes make direct access possible.

        A Temporal outage must not turn a successful object-storage write into
        a failed upload. ``index_status`` stays ``pending`` and an explicit
        retry remains available until the worker can process it.
        """

        upload = document.upload
        if upload is None or upload.status != "available":
            raise InvalidDocumentStateError("cannot index unavailable upload")
        try:
            await self._workflows.start_native_upload_indexing(
                NativeUploadIndexingInput(
                    document_id=str(document.id),
                    tenant_id=str(document.tenant_id),
                    owner_user_id=str(upload.owner_user_id),
                )
            )
        except Exception:  # noqa: BLE001 - raw-resource readiness is durable first
            log.exception("native upload indexing dispatch failed document_id=%s", document.id)

    async def _require_writable_collection(
        self,
        access: AuthContext,
        collection_id: UUID,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        if access.tenant_id is None:
            raise UploadValidationError("an active tenant is required")
        if session is None:
            async with self._session_factory() as owned_session:
                await self._require_writable_collection(
                    access, collection_id, session=owned_session
                )
            return
        collection = await AuthorizationService(session).require_item(
            collection_id,
            access=access,
            permission=COLLECTION_UPDATE_PERMISSION,
        )
        if collection.item_type != "collection":
            raise DocumentNotFoundError(f"collection not found: {collection_id}")
        if collection.status != "ready":
            raise UploadValidationError("collection is unavailable for uploads")

    async def _spool(
        self,
        content: AsyncUploadStream,
        file_name: str,
    ) -> tuple[Path, int]:
        temporary = tempfile.NamedTemporaryFile(
            prefix="bothesis-collection-upload-",
            suffix=Path(file_name).suffix,
            delete=False,
        )
        path = Path(temporary.name)
        size_bytes = 0
        try:
            while True:
                chunk = await content.read(min(1024 * 1024, self.max_upload_bytes + 1))
                if not chunk:
                    break
                size_bytes += len(chunk)
                self._validate_upload_size(size_bytes)
                temporary.write(chunk)
            temporary.flush()
            self._validate_upload_size(size_bytes)
            return path, size_bytes
        except Exception:
            temporary.close()
            path.unlink(missing_ok=True)
            raise
        finally:
            if not temporary.closed:
                temporary.close()

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


def _validate_supported_file(file_name: str) -> None:
    extension = Path(file_name).suffix.casefold()
    if extension not in FinxFileExtensions.ALL_ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"unsupported file type: {extension or 'file has no extension'}"
        )


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


__all__ = ["DocumentUploadService"]


def _document_type(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type == "application/pdf":
        return "pdf"
    if content_type in {"text/html", "application/xhtml+xml"}:
        return "web_page"
    if content_type in {"text/markdown", "text/x-markdown"}:
        return "markdown"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
        return "video"
    return "plain_text"
