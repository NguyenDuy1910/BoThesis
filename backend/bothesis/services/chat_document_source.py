"""Raw-source orchestration for indexed chat documents."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bothesis.connector.file import FileProcessingError, FileProcessor, ProcessedFile
from bothesis.connector.protocol import (
    AccessPolicy,
    DocumentKind,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.db.models import Item
from bothesis.storage import DocumentStorage
from bothesis.services import (
    AuthContext,
    CanonicalDocumentContent,
    DEFAULT_PROCESSING_MAX_BYTES,
    DocumentProcessingError,
    DocumentUnavailableError,
)


class ChatDocumentSourceService:
    """Resolve stored uploads and produce canonical connector evidence."""

    def __init__(
        self,
        *,
        object_storage: DocumentStorage,
        processor: FileProcessor,
        max_processing_bytes: int = DEFAULT_PROCESSING_MAX_BYTES,
    ) -> None:
        if max_processing_bytes < 1:
            raise ValueError("document processing limit must be greater than zero")
        self._object_storage = object_storage
        self._processor = processor
        self._max_processing_bytes = max_processing_bytes

    async def canonicalize(
        self,
        document: Item,
        *,
        access: AuthContext,
    ) -> CanonicalDocumentContent:
        """Stream or read one authorized upload through the file connector."""

        self._validate_size(document)
        if not document.storage_key:
            raise DocumentUnavailableError("item has no raw object storage key")
        with tempfile.TemporaryDirectory(prefix="bothesis-chat-document-") as directory:
            suffix = Path(self._file_name(document)).suffix
            path = Path(directory) / f"source{suffix}"
            stored = await self._object_storage.download_to_path(
                document.storage_key,
                path,
                max_bytes=self._max_processing_bytes,
            )
            self._validate_stored_size(document, stored.size_bytes)
            try:
                processed = await asyncio.to_thread(
                    self._processor.process_path,
                    path,
                    **self._processing_arguments(document, access=access),
                )
            except FileProcessingError as exc:
                raise DocumentProcessingError("document source processing failed") from exc
            return self._canonical_content(document, processed, access=access)

    async def direct_file_data(
        self,
        document: Item,
        *,
        expires_seconds: int,
    ) -> str:
        """Return a short-lived URL for the original object."""

        if expires_seconds < 1:
            raise ValueError("download URL lifetime must be greater than zero")
        self._validate_size(document)
        if not document.storage_key:
            raise DocumentUnavailableError("item has no raw object storage key")
        return self._object_storage.presign_download(
            document.storage_key, expires_seconds=expires_seconds
        ).url

    def _canonical_content(
        self,
        document: Item,
        processed: ProcessedFile,
        *,
        access: AuthContext,
    ) -> CanonicalDocumentContent:
        expected_item_id = str(document.id)
        if processed.item.id != expected_item_id:
            raise DocumentProcessingError(
                "canonical document ID does not match its stored source"
            )
        if any(chunk.item_id != expected_item_id for chunk in processed.chunks):
            raise DocumentProcessingError(
                "canonical chunk does not belong to its stored source"
            )
        if processed.item.access.effective.reader_ids != [str(access.user_id)]:
            raise DocumentProcessingError(
                "canonical document access does not match its authorized owner"
            )
        return CanonicalDocumentContent(
            item=processed.item,
            chunks=tuple(processed.chunks),
        )

    def _validate_size(self, document: Item) -> None:
        if (document.size_bytes or 0) > self._max_processing_bytes:
            raise DocumentProcessingError(
                "document exceeds the configured processing limit"
            )

    @staticmethod
    def _validate_stored_size(document: Item, size_bytes: int) -> None:
        if document.size_bytes is not None and size_bytes != document.size_bytes:
            raise DocumentUnavailableError(
                "stored document size no longer matches metadata"
            )

    @classmethod
    def _processing_arguments(
        cls,
        document: Item,
        *,
        access: AuthContext,
    ) -> dict[str, Any]:
        file_name = cls._file_name(document)
        return {
            "file_name": file_name,
            "item_id": str(document.id),
            "title": file_name,
            "source": SourceIdentity(
                connector_id="upload",
                provider=SourceProvider.FILE,
                external_id=str(document.id),
                external_version=None,
                etag=None,
                url=None,
            ),
            "document_kind": cls._document_kind(document.mime_type),
            "access": AccessPolicy.from_reader_ids([str(access.user_id)]),
            "hierarchy": Hierarchy(),
            "metadata": cls._source_metadata(document.metadata_),
        }

    @staticmethod
    def _file_name(document: Item) -> str:
        value = document.metadata_.get("file_name") or document.title or str(
            document.id
        )
        return str(value)

    @staticmethod
    def _source_metadata(
        metadata: Mapping[str, Any],
    ) -> dict[str, str | list[str]]:
        projected: dict[str, str | list[str]] = {}
        for key, value in metadata.items():
            if isinstance(value, str):
                projected[str(key)] = value
            elif isinstance(value, (list, tuple)) and all(
                isinstance(item, str) for item in value
            ):
                projected[str(key)] = list(value)
        return projected

    @staticmethod
    def _document_kind(content_type: str | None) -> DocumentKind:
        normalized = (content_type or "").casefold()
        if normalized.startswith("image/"):
            return DocumentKind.IMAGE
        if normalized == "application/pdf":
            return DocumentKind.PDF
        if normalized in {"text/html", "application/xhtml+xml"}:
            return DocumentKind.WEB_PAGE
        return DocumentKind.DOCUMENT


__all__ = ["ChatDocumentSourceService"]
