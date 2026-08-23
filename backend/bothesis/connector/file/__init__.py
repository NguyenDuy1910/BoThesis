"""Validated file-source processing and connector contracts."""

from __future__ import annotations

from dataclasses import dataclass

from bothesis.connector.protocol import Chunk, DocumentItem

DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_TEXT_CHARACTERS = 2_000_000
DEFAULT_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


class FileProcessingError(ValueError):
    """Base error for a file that cannot safely enter indexing."""


class UnsupportedFileTypeError(FileProcessingError):
    """Raised when a file format is outside the supported Docling boundary."""


class FileSizeLimitError(FileProcessingError):
    """Raised when source or expanded archive content exceeds its limit."""


class FileTextLimitError(FileProcessingError):
    """Raised when normalized semantic text exceeds its configured limit."""


class FinxFileExtensions:
    """File extension groups shared with source attachment adapters."""

    TEXT_EXTENSIONS = frozenset(
        {
            ".csv", ".htm", ".html", ".json", ".jsonl", ".log",
            ".markdown", ".md", ".rst", ".sql", ".tsv", ".txt",
            ".xml", ".yaml", ".yml",
        }
    )
    OFFICE_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})
    PDF_EXTENSIONS = frozenset({".pdf"})
    IMAGE_EXTENSIONS = frozenset(
        {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
    )
    TEXT_EXTRACTABLE_EXTENSIONS = TEXT_EXTENSIONS | OFFICE_EXTENSIONS | PDF_EXTENSIONS
    ALL_ALLOWED_EXTENSIONS = TEXT_EXTRACTABLE_EXTENSIONS | IMAGE_EXTENSIONS


class FinxMimeTypes:
    IMAGE_MIME_TYPES = frozenset(
        {
            "image/avif", "image/bmp", "image/gif", "image/jpeg", "image/png",
            "image/tiff", "image/webp",
        }
    )


@dataclass(frozen=True, slots=True)
class ProcessedFile:
    """Canonical output of one validated file-processing operation."""

    file_name: str
    text: str
    size_bytes: int
    sha256: str
    mime_type: str | None
    item: DocumentItem
    chunks: tuple[Chunk, ...]


from .file_connector import FileConnector, LocalFileConnector  # noqa: E402
from .processing import FileProcessor  # noqa: E402

__all__ = [
    "DEFAULT_MAX_ARCHIVE_BYTES", "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_TEXT_CHARACTERS", "FileConnector", "FileProcessingError",
    "FileProcessor", "FileSizeLimitError", "FileTextLimitError",
    "FinxFileExtensions", "FinxMimeTypes", "LocalFileConnector",
    "ProcessedFile", "UnsupportedFileTypeError",
]
