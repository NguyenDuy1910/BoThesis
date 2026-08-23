"""Configured Docling conversion owned by the connector boundary."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from docling.datamodel.base_models import ConversionStatus, DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import (
    DocumentConverter,
    ImageFormatOption,
    PdfFormatOption,
)
from docling_core.types.doc import (
    DescriptionAnnotation,
    DocItem,
    DocItemLabel,
    DoclingDocument,
    PictureItem,
    TableItem,
    TextItem,
)

from . import DoclingProcessingError


_DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
_DEFAULT_MAX_TEXT_CHARACTERS = 2_000_000
_DEFAULT_MAX_PAGES = 1_000

_PLAIN_TEXT_EXTENSIONS = frozenset(
    {
        ".json",
        ".jsonl",
        ".log",
        ".rst",
        ".sql",
        ".tsv",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
_LINE_SENSITIVE_EXTENSIONS = frozenset({".jsonl", ".log", ".sql", ".tsv"})
_CONVERTER_EXTENSIONS = frozenset(
    {
        ".avif",
        ".bmp",
        ".csv",
        ".docx",
        ".gif",
        ".htm",
        ".html",
        ".jpeg",
        ".jpg",
        ".markdown",
        ".md",
        ".pdf",
        ".png",
        ".pptx",
        ".tif",
        ".tiff",
        ".webp",
        ".xlsx",
    }
)


class DoclingProcessor:
    """Convert bounded path/byte inputs with one reusable Docling converter."""

    def __init__(
        self,
        *,
        converter: Any | None = None,
        do_ocr: bool = True,
        do_table_structure: bool = True,
        do_picture_description: bool = False,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
        max_text_characters: int = _DEFAULT_MAX_TEXT_CHARACTERS,
        max_num_pages: int = _DEFAULT_MAX_PAGES,
        page_range: tuple[int, int] | None = None,
        allow_partial: bool = False,
    ) -> None:
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        if max_text_characters < 1:
            raise ValueError("max_text_characters must be positive")
        if max_num_pages < 1:
            raise ValueError("max_num_pages must be positive")
        resolved_page_range = page_range or (1, max_num_pages)
        if (
            len(resolved_page_range) != 2
            or resolved_page_range[0] < 1
            or resolved_page_range[1] < resolved_page_range[0]
        ):
            raise ValueError("page_range must be an inclusive positive (start, end) pair")
        if resolved_page_range[1] - resolved_page_range[0] + 1 > max_num_pages:
            raise ValueError("page_range cannot contain more than max_num_pages")

        self.max_file_bytes = max_file_bytes
        self.max_text_characters = max_text_characters
        self.max_num_pages = max_num_pages
        self.page_range = resolved_page_range
        self.allow_partial = allow_partial
        self._converter = converter or _configured_converter(
            do_ocr=do_ocr,
            do_table_structure=do_table_structure,
            do_picture_description=do_picture_description,
        )

    def process_path(
        self,
        path: str | Path,
        *,
        file_name: str | None = None,
    ) -> DoclingDocument:
        source = Path(path)
        if not source.is_file():
            raise DoclingProcessingError(f"Document path is not a file: {source}")
        self._validate_size(source.stat().st_size, file_name=file_name or source.name)
        resolved_name = _file_name(file_name or source.name)
        if _extension(resolved_name) in _PLAIN_TEXT_EXTENSIONS:
            return self.process_text(source.read_bytes(), file_name=resolved_name)
        if (
            file_name is not None
            and _extension(resolved_name) != _extension(source.name)
        ) or _extension(resolved_name) in {".htm", ".markdown"}:
            return self.process_bytes(source.read_bytes(), file_name=resolved_name)
        self._validate_converter_extension(resolved_name)
        return self._convert(source, file_name=resolved_name)

    def process_bytes(self, data: bytes, *, file_name: str) -> DoclingDocument:
        resolved_name = _file_name(file_name)
        self._validate_size(len(data), file_name=resolved_name)
        if not data:
            raise DoclingProcessingError(f"Document is empty: {resolved_name}")
        if _extension(resolved_name) in _PLAIN_TEXT_EXTENSIONS:
            return self.process_text(data, file_name=resolved_name)
        self._validate_converter_extension(resolved_name)
        stream = DocumentStream(name=_converter_file_name(resolved_name), stream=BytesIO(data))
        return self._convert(stream, file_name=resolved_name)

    def process_text(self, data: bytes, *, file_name: str) -> DoclingDocument:
        """Build a Docling document for formats without a Docling backend."""

        resolved_name = _file_name(file_name)
        extension = _extension(resolved_name)
        if extension not in _PLAIN_TEXT_EXTENSIONS:
            raise DoclingProcessingError(
                f"Text processing does not support extension {extension or '<none>'}"
            )
        self._validate_size(len(data), file_name=resolved_name)
        if not data:
            raise DoclingProcessingError(f"Document is empty: {resolved_name}")
        try:
            decoded = _decode_text(data)
            text = _normalized_text(decoded, extension=extension)
        except (UnicodeError, json.JSONDecodeError, ElementTree.ParseError) as exc:
            raise DoclingProcessingError(
                f"Invalid {extension.removeprefix('.').upper()} document: {resolved_name}"
            ) from exc
        if len(text) > self.max_text_characters:
            raise DoclingProcessingError(
                f"Extracted text exceeds {self.max_text_characters} characters: {resolved_name}"
            )
        if not text:
            raise DoclingProcessingError(
                f"No extractable content found in {resolved_name}"
            )
        document = DoclingDocument(name=resolved_name)
        if extension in _LINE_SENSITIVE_EXTENSIONS:
            for line in text.splitlines():
                if line.strip():
                    document.add_text(label=DocItemLabel.TEXT, text=line)
        else:
            document.add_text(label=DocItemLabel.TEXT, text=text)
        return document

    def _convert(self, source: Any, *, file_name: str) -> DoclingDocument:
        try:
            result = self._converter.convert(
                source,
                raises_on_error=False,
                max_num_pages=self.max_num_pages,
                max_file_size=self.max_file_bytes,
                page_range=self.page_range,
            )
        except Exception as exc:
            raise DoclingProcessingError(
                f"Docling could not process {file_name}"
            ) from exc

        status = getattr(result, "status", None)
        successful = status == ConversionStatus.SUCCESS
        partial = status == ConversionStatus.PARTIAL_SUCCESS
        if not successful and not (partial and self.allow_partial):
            detail = _conversion_error_detail(getattr(result, "errors", ()))
            status_value = getattr(status, "value", str(status or "unknown"))
            suffix = f": {detail}" if detail else ""
            raise DoclingProcessingError(
                f"Docling conversion {status_value} for {file_name}{suffix}"
            )
        document = getattr(result, "document", None)
        if not isinstance(document, DoclingDocument):
            raise DoclingProcessingError(
                f"Docling returned no document for {file_name}"
            )
        if not any(
            isinstance(item, DocItem)
            for item, _ in document.iterate_items(traverse_pictures=False)
        ):
            raise DoclingProcessingError(
                f"No extractable content found in {file_name}"
            )
        text_characters = _document_text_characters(document)
        if text_characters > self.max_text_characters:
            raise DoclingProcessingError(
                f"Extracted text exceeds {self.max_text_characters} characters: {file_name}"
            )
        return document

    def _validate_size(self, size_bytes: int, *, file_name: str) -> None:
        if size_bytes > self.max_file_bytes:
            raise DoclingProcessingError(
                f"File exceeds {self.max_file_bytes} byte limit: {file_name}"
            )

    @staticmethod
    def _validate_converter_extension(file_name: str) -> None:
        extension = _extension(file_name)
        if extension not in _CONVERTER_EXTENSIONS:
            raise DoclingProcessingError(
                f"Unsupported file extension {extension or '<none>'}"
            )


def _configured_converter(
    *,
    do_ocr: bool,
    do_table_structure: bool,
    do_picture_description: bool,
) -> DocumentConverter:
    pipeline_options = PdfPipelineOptions(
        do_ocr=do_ocr,
        do_table_structure=do_table_structure,
        do_picture_description=do_picture_description,
        generate_page_images=False,
        generate_picture_images=False,
    )
    allowed_formats = [
        InputFormat.PDF,
        InputFormat.DOCX,
        InputFormat.PPTX,
        InputFormat.XLSX,
        InputFormat.HTML,
        InputFormat.IMAGE,
        InputFormat.MD,
        InputFormat.CSV,
    ]
    return DocumentConverter(
        allowed_formats=allowed_formats,
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
        },
    )


def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        value = data.decode("utf-16")
    else:
        value = data.decode("utf-8-sig")
    if "\x00" in value:
        raise UnicodeError("text document contains null bytes")
    return value


def _normalized_text(value: str, *, extension: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if extension == ".json":
        return json.dumps(
            json.loads(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    if extension == ".jsonl":
        return "\n".join(
            json.dumps(
                json.loads(line),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for line in value.splitlines()
            if line.strip()
        )
    if extension == ".xml":
        root = ElementTree.fromstring(value)
        return "\n".join(text.strip() for text in root.itertext() if text.strip())
    return value.strip()


def _conversion_error_detail(errors: Any) -> str:
    values = []
    for error in errors or ():
        message = str(getattr(error, "error_message", "") or "").strip()
        if message:
            values.append(message)
    return "; ".join(values[:3])


def _document_text_characters(document: DoclingDocument) -> int:
    total = 0
    for item, _ in document.iterate_items(traverse_pictures=False):
        if isinstance(item, TextItem):
            total += len(item.text)
        elif isinstance(item, TableItem):
            total += sum(len(cell.text) for cell in item.data.table_cells)
        elif isinstance(item, PictureItem):
            total += sum(
                len(annotation.text)
                for annotation in item.__dict__.get("annotations", ())
                if isinstance(annotation, DescriptionAnnotation)
            )
    return total


def _file_name(value: str) -> str:
    normalized = value.strip()
    if not normalized or "\x00" in normalized:
        raise DoclingProcessingError("file_name must not be blank")
    return Path(normalized).name


def _extension(file_name: str) -> str:
    return Path(file_name).suffix.casefold()


def _converter_file_name(file_name: str) -> str:
    extension = _extension(file_name)
    if extension == ".markdown":
        return f"{Path(file_name).stem}.md"
    if extension == ".htm":
        return f"{Path(file_name).stem}.html"
    return file_name


__all__ = ["DoclingProcessor"]
