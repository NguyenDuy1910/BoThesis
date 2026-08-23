"""Validated file-to-canonical processing through Docling."""

from __future__ import annotations

import hashlib
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from bothesis.connector.file import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_TEXT_CHARACTERS,
    FileProcessingError,
    FileSizeLimitError,
    FileTextLimitError,
    FinxFileExtensions,
    ProcessedFile,
    UnsupportedFileTypeError,
)
from bothesis.connector.processing import (
    DoclingChunker,
    DoclingChunkingError,
    DoclingProcessingError,
    DoclingProcessor,
    DocumentMapper,
)
from bothesis.connector.protocol import (
    AccessPolicy,
    DocumentKind,
    Hierarchy,
    ImagePart,
    SourceIdentity,
    SourceProvider,
    StorageObject,
)

_LINE_SENSITIVE_EXTENSIONS = frozenset({".jsonl", ".log", ".sql", ".tsv"})


class FileProcessor:
    """Validate, convert, normalize, and chunk one source file with Docling."""

    def __init__(
        self,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_text_characters: int = DEFAULT_MAX_TEXT_CHARACTERS,
        max_archive_uncompressed_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
        docling: DoclingProcessor | None = None,
        mapper: DocumentMapper | None = None,
        chunker: DoclingChunker | None = None,
    ) -> None:
        if min(max_file_bytes, max_text_characters, max_archive_uncompressed_bytes) < 1:
            raise ValueError("file processing limits must be greater than zero")
        self.max_file_bytes = max_file_bytes
        self.max_text_characters = max_text_characters
        self.max_archive_uncompressed_bytes = max_archive_uncompressed_bytes
        self._docling = docling or DoclingProcessor(
            max_file_bytes=max_file_bytes,
            max_text_characters=max_text_characters,
        )
        self._mapper = mapper or DocumentMapper()
        self._chunker = chunker or DoclingChunker()

    def process_path(
        self,
        path: Path,
        *,
        file_name: str | None = None,
        item_id: str | None = None,
        title: str | None = None,
        source: SourceIdentity | None = None,
        document_kind: DocumentKind | None = None,
        access: AccessPolicy | None = None,
        hierarchy: Hierarchy | None = None,
        metadata: dict[str, str | list[str]] | None = None,
        original: StorageObject | None = None,
    ) -> ProcessedFile:
        source_path = Path(path)
        if not source_path.is_file():
            raise FileProcessingError(f"Document path is not a file: {source_path}")
        resolved_name = _file_name(file_name or source_path.name)
        size_bytes = source_path.stat().st_size
        self._validate_input(resolved_name, size_bytes=size_bytes)
        self._validate_archive_path(source_path, extension=_extension(resolved_name))
        digest = _sha256_path(source_path)
        try:
            # The path's extension is retained by upload/storage flows. Avoid
            # passing a display-name override because Docling would otherwise
            # materialize a second full byte buffer solely to rename the input.
            document = self._docling.process_path(source_path)
        except DoclingProcessingError as exc:
            raise _file_error(exc) from exc
        return self._canonical_output(
            document,
            file_name=resolved_name,
            size_bytes=size_bytes,
            digest=digest,
            item_id=item_id,
            title=title,
            source=source,
            document_kind=document_kind,
            access=access,
            hierarchy=hierarchy,
            metadata=metadata,
            original=original,
        )

    def process_bytes(
        self,
        data: bytes,
        *,
        file_name: str,
        item_id: str | None = None,
        title: str | None = None,
        source: SourceIdentity | None = None,
        document_kind: DocumentKind | None = None,
        access: AccessPolicy | None = None,
        hierarchy: Hierarchy | None = None,
        metadata: dict[str, str | list[str]] | None = None,
        original: StorageObject | None = None,
    ) -> ProcessedFile:
        resolved_name = _file_name(file_name)
        self._validate_input(resolved_name, size_bytes=len(data))
        self._validate_archive_bytes(data, extension=_extension(resolved_name))
        digest = hashlib.sha256(data).hexdigest()
        try:
            document = self._docling.process_bytes(data, file_name=resolved_name)
        except DoclingProcessingError as exc:
            raise _file_error(exc) from exc
        return self._canonical_output(
            document,
            file_name=resolved_name,
            size_bytes=len(data),
            digest=digest,
            item_id=item_id,
            title=title,
            source=source,
            document_kind=document_kind,
            access=access,
            hierarchy=hierarchy,
            metadata=metadata,
            original=original,
        )

    def _canonical_output(
        self,
        document: Any,
        *,
        file_name: str,
        size_bytes: int,
        digest: str,
        item_id: str | None,
        title: str | None,
        source: SourceIdentity | None,
        document_kind: DocumentKind | None,
        access: AccessPolicy | None,
        hierarchy: Hierarchy | None,
        metadata: dict[str, str | list[str]] | None,
        original: StorageObject | None,
    ) -> ProcessedFile:
        resolved_id = item_id or f"file::{digest}"
        mime_type = mimetypes.guess_type(file_name)[0]
        resolved_source = source or SourceIdentity(
            connector_id=SourceProvider.FILE.value,
            provider=SourceProvider.FILE,
            external_id=resolved_id,
            external_version=digest,
            etag=digest,
        )
        resolved_metadata = {
            **(metadata or {}),
            "file_name": file_name,
            "sha256": digest,
        }
        resolved_kind = document_kind or _document_kind(mime_type)
        item = self._mapper.to_item(
            document,
            item_id=resolved_id,
            title=title or file_name,
            source=resolved_source,
            document_kind=resolved_kind,
            access=access,
            hierarchy=hierarchy,
            metadata=resolved_metadata,
            original=original,
        )
        text = item.get_text_content()
        if len(text) > self.max_text_characters:
            raise FileTextLimitError(
                f"Extracted text exceeds {self.max_text_characters} characters: {file_name}"
            )
        if (
            resolved_kind == DocumentKind.IMAGE
            and not any(isinstance(part, ImagePart) for part in item.content)
        ):
            raise FileProcessingError(
                f"Docling returned no image content for {file_name}"
            )
        if not text.strip() and resolved_kind != DocumentKind.IMAGE:
            raise FileProcessingError(f"No extractable content found in {file_name}")
        chunks = ()
        if text.strip():
            try:
                chunks = tuple(
                    self._chunker.chunk(
                        document,
                        item_id=resolved_id,
                        strategy=(
                            "line"
                            if _extension(file_name) in _LINE_SENSITIVE_EXTENSIONS
                            else "hybrid"
                        ),
                    )
                )
            except DoclingChunkingError as exc:
                raise FileProcessingError(str(exc)) from exc
        return ProcessedFile(
            file_name=file_name,
            text=text,
            size_bytes=size_bytes,
            sha256=digest,
            mime_type=mime_type,
            item=item,
            chunks=chunks,
        )

    def _validate_input(self, file_name: str, *, size_bytes: int) -> None:
        if size_bytes < 1:
            raise FileProcessingError(f"Document is empty: {file_name}")
        if size_bytes > self.max_file_bytes:
            raise FileSizeLimitError(
                f"File exceeds {self.max_file_bytes} byte limit: {size_bytes} bytes"
            )
        extension = _extension(file_name)
        if extension not in FinxFileExtensions.ALL_ALLOWED_EXTENSIONS:
            raise UnsupportedFileTypeError(
                f"Unsupported file extension {extension or '<none>'}"
            )

    def _validate_archive_path(self, path: Path, *, extension: str) -> None:
        if extension not in FinxFileExtensions.OFFICE_EXTENSIONS:
            return
        try:
            with ZipFile(path) as archive:
                self._validate_archive_members(archive)
        except BadZipFile as exc:
            raise FileProcessingError("Invalid Office Open XML archive") from exc

    def _validate_archive_bytes(self, data: bytes, *, extension: str) -> None:
        if extension not in FinxFileExtensions.OFFICE_EXTENSIONS:
            return
        try:
            with ZipFile(BytesIO(data)) as archive:
                self._validate_archive_members(archive)
        except BadZipFile as exc:
            raise FileProcessingError("Invalid Office Open XML archive") from exc

    def _validate_archive_members(self, archive: ZipFile) -> None:
        members = archive.infolist()
        if any(member.flag_bits & 0x1 for member in members):
            raise FileProcessingError("Encrypted Office archives are not supported")
        expanded = sum(member.file_size for member in members)
        if expanded > self.max_archive_uncompressed_bytes:
            raise FileSizeLimitError(
                "Office archive expands beyond the configured size limit"
            )


def _file_error(exc: DoclingProcessingError) -> FileProcessingError:
    message = str(exc)
    normalized = message.casefold()
    if "unsupported file extension" in normalized:
        return UnsupportedFileTypeError(message)
    if "characters" in normalized and "exceeds" in normalized:
        return FileTextLimitError(message)
    if "byte limit" in normalized or "file exceeds" in normalized:
        return FileSizeLimitError(message)
    return FileProcessingError(message)


def _file_name(value: str) -> str:
    normalized = value.strip()
    if not normalized or "\x00" in normalized:
        raise FileProcessingError("file_name must not be blank")
    return Path(normalized).name


def _extension(file_name: str) -> str:
    return Path(file_name).suffix.casefold()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _document_kind(mime_type: str | None) -> DocumentKind:
    normalized = (mime_type or "").casefold()
    if normalized.startswith("image/"):
        return DocumentKind.IMAGE
    if normalized == "application/pdf":
        return DocumentKind.PDF
    if normalized in {"text/html", "application/xhtml+xml"}:
        return DocumentKind.WEB_PAGE
    return DocumentKind.DOCUMENT


__all__ = ["FileProcessor"]
