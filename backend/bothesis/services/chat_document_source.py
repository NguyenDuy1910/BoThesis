"""Raw-source orchestration for indexed chat documents."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.connector.file import FileProcessingError, FileProcessor, ProcessedFile
from bothesis.connector.protocol import (
    AccessPolicy,
    DocumentKind,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.db.models import Document
from bothesis.document_index import (
    DocumentProcessingError,
    DocumentUnavailableError,
)
from bothesis.document_index.raw_storage import DocumentStorage, PostgresBlobStorage
from bothesis.services import (
    AuthContext,
    CanonicalDocumentContent,
    DEFAULT_PROCESSING_MAX_BYTES,
)


class ChatDocumentSourceService:
    """Resolve stored uploads and produce canonical connector evidence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        object_storage: DocumentStorage | None,
        processor: FileProcessor,
        max_processing_bytes: int = DEFAULT_PROCESSING_MAX_BYTES,
    ) -> None:
        if max_processing_bytes < 1:
            raise ValueError("document processing limit must be greater than zero")
        self._session_factory = session_factory
        self._object_storage = object_storage
        self._processor = processor
        self._max_processing_bytes = max_processing_bytes

    async def canonicalize(
        self,
        document: Document,
        *,
        access: AuthContext,
    ) -> CanonicalDocumentContent:
        """Stream or read one authorized upload through the file connector."""

        self._validate_size(document)
        if document.raw_storage_key:
            if self._object_storage is None:
                raise DocumentUnavailableError("object storage is unavailable")
            with tempfile.TemporaryDirectory(
                prefix="bothesis-chat-document-"
            ) as directory:
                suffix = Path(self._file_name(document)).suffix
                path = Path(directory) / f"source{suffix}"
                stored = await self._object_storage.download_to_path(
                    document.raw_storage_key,
                    path,
                    max_bytes=self._max_processing_bytes,
                )
                self._validate_stored_size(document, stored.size_bytes)
                digest = stored.checksum_sha256 or self._sha256_path(path)
                try:
                    processed = await asyncio.to_thread(
                        self._processor.process_path,
                        path,
                        **self._processing_arguments(
                            document,
                            access=access,
                            digest=digest,
                        ),
                    )
                except FileProcessingError as exc:
                    raise DocumentProcessingError(
                        "document source processing failed"
                    ) from exc
                return self._canonical_content(
                    document,
                    processed,
                    digest=digest,
                    access=access,
                )

        raw_bytes = await self._read_raw(document)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        try:
            processed = await asyncio.to_thread(
                self._processor.process_bytes,
                raw_bytes,
                **self._processing_arguments(
                    document,
                    access=access,
                    digest=digest,
                ),
            )
        except FileProcessingError as exc:
            raise DocumentProcessingError(
                "document source processing failed"
            ) from exc
        return self._canonical_content(
            document,
            processed,
            digest=digest,
            access=access,
        )

    async def direct_file_data(
        self,
        document: Document,
        *,
        expires_seconds: int,
    ) -> str:
        """Return a short-lived object URL or bounded database-backed data URI."""

        if expires_seconds < 1:
            raise ValueError("download URL lifetime must be greater than zero")
        self._validate_size(document)
        if document.raw_storage_key:
            if self._object_storage is None:
                raise DocumentUnavailableError("object storage is unavailable")
            return self._object_storage.presign_download(
                document.raw_storage_key,
                expires_seconds=expires_seconds,
            ).url
        content_type = document.mime_type or "application/octet-stream"
        raw_bytes = await self._read_raw(document)
        return f"data:{content_type};base64," + base64.b64encode(raw_bytes).decode(
            "ascii"
        )

    async def soft_delete_raw(
        self,
        document_id: UUID,
        *,
        session: AsyncSession,
    ) -> None:
        """Tombstone the PostgreSQL raw-byte fallback for a deleted upload."""

        await PostgresBlobStorage(session).soft_delete(document_id)

    async def _read_raw(self, document: Document) -> bytes:
        self._validate_size(document)
        if document.raw_storage_key:
            if self._object_storage is None:
                raise DocumentUnavailableError("object storage is unavailable")
            raw_bytes = await self._object_storage.read(
                document.raw_storage_key,
                max_bytes=self._max_processing_bytes,
            )
        else:
            async with self._session_factory() as session:
                raw_bytes = await PostgresBlobStorage(session).read(document.id)
        self._validate_stored_size(document, len(raw_bytes))
        return raw_bytes

    def _canonical_content(
        self,
        document: Document,
        processed: ProcessedFile,
        *,
        digest: str,
        access: AuthContext,
    ) -> CanonicalDocumentContent:
        if processed.sha256 != digest:
            raise DocumentProcessingError(
                "processed document checksum does not match its source"
            )
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
            source_fingerprint=digest,
        )

    def _validate_size(self, document: Document) -> None:
        if (document.size_bytes or 0) > self._max_processing_bytes:
            raise DocumentProcessingError(
                "document exceeds the configured processing limit"
            )

    @staticmethod
    def _validate_stored_size(document: Document, size_bytes: int) -> None:
        if document.size_bytes is not None and size_bytes != document.size_bytes:
            raise DocumentUnavailableError(
                "stored document size no longer matches metadata"
            )

    @classmethod
    def _processing_arguments(
        cls,
        document: Document,
        *,
        access: AuthContext,
        digest: str,
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
                external_version=digest,
                etag=digest,
                url=document.source_url,
            ),
            "document_kind": cls._document_kind(document.mime_type),
            "access": AccessPolicy.from_reader_ids([str(access.user_id)]),
            "hierarchy": Hierarchy(),
            "metadata": cls._source_metadata(document.metadata_),
        }

    @staticmethod
    def _file_name(document: Document) -> str:
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
    def _sha256_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

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
