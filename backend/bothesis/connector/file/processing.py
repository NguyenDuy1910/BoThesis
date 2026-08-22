"""Validated, reusable file parsing for connector and upload pipelines."""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from bothesis.knowledge.protocol import BoundingBox

DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_TEXT_CHARACTERS = 2_000_000
DEFAULT_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


class FileProcessingError(ValueError):
    """Base error for a file that cannot safely enter the indexing pipeline."""


class UnsupportedFileTypeError(FileProcessingError):
    pass


class FileSizeLimitError(FileProcessingError):
    pass


class FileTextLimitError(FileProcessingError):
    pass


class FinxFileExtensions:
    """Compatibility names used by the source-specific attachment adapters."""

    TEXT_EXTENSIONS = frozenset(
        {
            ".csv",
            ".htm",
            ".html",
            ".json",
            ".jsonl",
            ".log",
            ".markdown",
            ".md",
            ".rst",
            ".sql",
            ".tsv",
            ".txt",
            ".xml",
            ".yaml",
            ".yml",
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
            "image/avif",
            "image/bmp",
            "image/gif",
            "image/jpeg",
            "image/png",
            "image/tiff",
            "image/webp",
        }
    )


@dataclass(frozen=True, slots=True)
class ProcessedFile:
    file_name: str
    text: str
    raw_bytes: bytes
    size_bytes: int
    sha256: str
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class ParsedSection:
    """One source-preserving unit produced before deterministic chunking."""

    content: str
    element_id: str | None = None
    page_number: int | None = None
    heading_path: tuple[str, ...] | None = None
    bounding_box: BoundingBox | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    file_name: str
    sections: tuple[ParsedSection, ...]
    raw_bytes: bytes
    size_bytes: int
    sha256: str
    mime_type: str | None

    @property
    def text(self) -> str:
        return "\n\n".join(section.content for section in self.sections)


Extractor = Callable[[bytes, str], str]


class FileProcessor:
    """Extract text with size limits and an injectable format registry.

    PDF extraction is loaded lazily through ``pypdf``. Deployments that do not
    index PDFs can use this module without that optional package; PDF-enabled
    workers receive a clear configuration error if it is absent.
    """

    def __init__(
        self,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_text_characters: int = DEFAULT_MAX_TEXT_CHARACTERS,
        max_archive_uncompressed_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
        extractors: Mapping[str, Extractor] | None = None,
    ) -> None:
        if min(max_file_bytes, max_text_characters, max_archive_uncompressed_bytes) < 1:
            raise ValueError("file processing limits must be greater than zero")
        self.max_file_bytes = max_file_bytes
        self.max_text_characters = max_text_characters
        self.max_archive_uncompressed_bytes = max_archive_uncompressed_bytes
        self._custom_extractors = {
            _normalise_extension(extension): extractor
            for extension, extractor in (extractors or {}).items()
        }

    def process_path(
        self, path: Path, *, file_name: str | None = None
    ) -> ProcessedFile:
        size_bytes = path.stat().st_size
        self._validate_size(size_bytes)
        return self.process_bytes(path.read_bytes(), file_name=file_name or path.name)

    def process_bytes(self, data: bytes, *, file_name: str) -> ProcessedFile:
        parsed = self.parse_bytes(data, file_name=file_name)
        return ProcessedFile(
            file_name=parsed.file_name,
            text=parsed.text,
            raw_bytes=parsed.raw_bytes,
            size_bytes=parsed.size_bytes,
            sha256=parsed.sha256,
            mime_type=parsed.mime_type,
        )

    def parse_bytes(self, data: bytes, *, file_name: str) -> ParsedDocument:
        """Parse raw content into sections while retaining page/sheet lineage."""

        self._validate_size(len(data))
        extension = _normalise_extension(Path(file_name).suffix)
        extractor = self._custom_extractors.get(extension)
        if extractor is not None:
            raw_sections = [ParsedSection(content=extractor(data, file_name))]
        else:
            raw_sections = self._default_sections(data, file_name, extension)
        sections = tuple(
            ParsedSection(
                content=_normalise_text(section.content),
                element_id=section.element_id,
                page_number=section.page_number,
                heading_path=section.heading_path,
                bounding_box=section.bounding_box,
                metadata=dict(section.metadata or {}),
            )
            for section in raw_sections
            if _normalise_text(section.content)
        )
        text_length = sum(len(section.content) for section in sections)
        if text_length > self.max_text_characters:
            raise FileTextLimitError(
                f"Extracted text exceeds {self.max_text_characters} characters: {file_name}"
            )
        if not sections:
            raise FileProcessingError(f"No extractable text found in {file_name}")
        return ParsedDocument(
            file_name=file_name,
            sections=sections,
            raw_bytes=data,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            mime_type=mimetypes.guess_type(file_name)[0],
        )

    def _validate_size(self, size_bytes: int) -> None:
        if size_bytes > self.max_file_bytes:
            raise FileSizeLimitError(
                f"File exceeds {self.max_file_bytes} byte limit: {size_bytes} bytes"
            )

    def _default_extractor(self, extension: str) -> Extractor:
        if extension in FinxFileExtensions.TEXT_EXTENSIONS:
            if extension in {".htm", ".html"}:
                return _extract_html
            if extension == ".xml":
                return _extract_xml
            if extension == ".json":
                return _extract_json
            return _extract_plain_text
        if extension == ".docx":
            return lambda data, _: _extract_docx(
                data, max_uncompressed_bytes=self.max_archive_uncompressed_bytes
            )
        if extension == ".pptx":
            return lambda data, _: _extract_pptx(
                data, max_uncompressed_bytes=self.max_archive_uncompressed_bytes
            )
        if extension == ".xlsx":
            return lambda data, _: _extract_xlsx(
                data, max_uncompressed_bytes=self.max_archive_uncompressed_bytes
            )
        if extension == ".pdf":
            return _extract_pdf
        raise UnsupportedFileTypeError(
            f"Unsupported file extension {extension or '<none>'}"
        )

    def _default_sections(
        self,
        data: bytes,
        file_name: str,
        extension: str,
    ) -> list[ParsedSection]:
        if extension == ".pdf":
            return _extract_pdf_sections(data)
        if extension == ".xlsx":
            return _extract_xlsx_sections(
                data,
                max_uncompressed_bytes=self.max_archive_uncompressed_bytes,
            )
        if extension == ".pptx":
            return _extract_pptx_sections(
                data,
                max_uncompressed_bytes=self.max_archive_uncompressed_bytes,
            )
        if extension == ".docx":
            return _extract_docx_sections(
                data,
                max_uncompressed_bytes=self.max_archive_uncompressed_bytes,
            )
        extractor = self._default_extractor(extension)
        return [ParsedSection(content=extractor(data, file_name))]


def extract_file_text(file: BinaryIO, file_name: str) -> str:
    """Compatibility wrapper used by Confluence and Jira attachments."""

    return FileProcessor().process_bytes(file.read(), file_name=file_name).text


def _normalise_extension(value: str) -> str:
    extension = value.strip().lower()
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    return extension


def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig", errors="replace")


def _extract_plain_text(data: bytes, _: str) -> str:
    return _decode_text(data)


def _extract_json(data: bytes, _: str) -> str:
    decoded = _decode_text(data)
    try:
        return json.dumps(json.loads(decoded), ensure_ascii=False, indent=2)
    except json.JSONDecodeError as exc:
        raise FileProcessingError(f"Invalid JSON: {exc.msg}") from exc


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "template"}:
            self._hidden_depth += 1
        elif not self._hidden_depth and tag in {
            "br",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "li",
            "p",
            "tr",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _extract_html(data: bytes, _: str) -> str:
    parser = _VisibleHTMLParser()
    parser.feed(_decode_text(data))
    return html.unescape("".join(parser.parts))


def _extract_xml(data: bytes, _: str) -> str:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise FileProcessingError(f"Invalid XML: {exc}") from exc
    return "\n".join(part.strip() for part in root.itertext() if part.strip())


def _safe_archive(data: bytes, max_uncompressed_bytes: int) -> ZipFile:
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise FileProcessingError("Invalid Office Open XML archive") from exc
    total_size = sum(member.file_size for member in archive.infolist())
    if total_size > max_uncompressed_bytes:
        archive.close()
        raise FileSizeLimitError(
            f"Expanded archive exceeds {max_uncompressed_bytes} byte limit"
        )
    return archive


def _xml_text(data: bytes, *, text_suffix: str = "}t") -> list[str]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise FileProcessingError(f"Invalid Office XML: {exc}") from exc
    return [node.text or "" for node in root.iter() if node.tag.endswith(text_suffix)]


def _extract_docx(data: bytes, *, max_uncompressed_bytes: int) -> str:
    return "\n\n".join(
        section.content
        for section in _extract_docx_sections(
            data,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )
    )


def _extract_docx_sections(
    data: bytes,
    *,
    max_uncompressed_bytes: int,
) -> list[ParsedSection]:
    with _safe_archive(data, max_uncompressed_bytes) as archive:
        if "word/document.xml" not in archive.namelist():
            raise FileProcessingError("DOCX archive has no document body")
        try:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        except ElementTree.ParseError as exc:
            raise FileProcessingError("Invalid DOCX document XML") from exc

        sections: list[ParsedSection] = []
        heading_path: list[str] = []
        paragraphs: list[str] = []

        def flush() -> None:
            if not paragraphs:
                return
            element_id = f"paragraph_{len(sections) + 1:03d}"
            sections.append(
                ParsedSection(
                    content="\n".join(paragraphs),
                    element_id=element_id,
                    heading_path=tuple(heading_path) or None,
                    metadata={"section_type": "docx_body"},
                )
            )
            paragraphs.clear()

        for paragraph in (node for node in root.iter() if node.tag.endswith("}p")):
            text_content = " ".join(
                node.text or "" for node in paragraph.iter() if node.tag.endswith("}t")
            ).strip()
            if not text_content:
                continue
            heading_level = _docx_heading_level(paragraph)
            if heading_level is not None:
                flush()
                heading_path[heading_level - 1 :] = [text_content]
                paragraphs.append(text_content)
                continue
            paragraphs.append(text_content)
        flush()

        for name in archive.namelist():
            match = re.fullmatch(r"word/(header|footer)(\d+)\.xml", name)
            if not match:
                continue
            content = " ".join(part for part in _xml_text(archive.read(name)) if part)
            if content.strip():
                label = f"{match.group(1).title()} {match.group(2)}"
                sections.append(
                    ParsedSection(
                        content=content,
                        element_id=f"{match.group(1)}_{match.group(2)}",
                        heading_path=(label,),
                        metadata={"section_type": match.group(1)},
                    )
                )
        return sections


def _docx_heading_level(paragraph: ElementTree.Element) -> int | None:
    for node in paragraph.iter():
        if not node.tag.endswith("}pStyle"):
            continue
        style = next(
            (value for key, value in node.attrib.items() if key.endswith("}val")),
            "",
        )
        match = re.fullmatch(r"heading\s*([1-9])", style, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _numeric_archive_names(archive: ZipFile, pattern: str) -> list[str]:
    matched: list[tuple[int, str]] = []
    regex = re.compile(pattern)
    for name in archive.namelist():
        match = regex.fullmatch(name)
        if match:
            matched.append((int(match.group(1)), name))
    return [name for _, name in sorted(matched)]


def _extract_pptx(data: bytes, *, max_uncompressed_bytes: int) -> str:
    return "\n\n".join(
        section.content
        for section in _extract_pptx_sections(
            data,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )
    )


def _extract_pptx_sections(
    data: bytes,
    *,
    max_uncompressed_bytes: int,
) -> list[ParsedSection]:
    with _safe_archive(data, max_uncompressed_bytes) as archive:
        slides = _numeric_archive_names(archive, r"ppt/slides/slide(\d+)\.xml")
        return [
            ParsedSection(
                content="\n".join(
                    part for part in _xml_text(archive.read(name)) if part
                ),
                heading_path=(f"Slide {index}",),
                metadata={"slide_number": index},
            )
            for index, name in enumerate(slides, 1)
        ]


def _extract_xlsx(data: bytes, *, max_uncompressed_bytes: int) -> str:
    return "\n\n".join(
        section.content
        for section in _extract_xlsx_sections(
            data,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )
    )


def _extract_xlsx_sections(
    data: bytes,
    *,
    max_uncompressed_bytes: int,
) -> list[ParsedSection]:
    with _safe_archive(data, max_uncompressed_bytes) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_strings = _xlsx_shared_strings(archive.read("xl/sharedStrings.xml"))
        sheets = _numeric_archive_names(archive, r"xl/worksheets/sheet(\d+)\.xml")
        display_names = _xlsx_sheet_names(archive)
        display_name_by_path = _xlsx_sheet_name_map(archive)
        output: list[ParsedSection] = []
        for index, sheet_path in enumerate(sheets, 1):
            root = ElementTree.fromstring(archive.read(sheet_path))
            rows: list[str] = []
            for row in (node for node in root.iter() if node.tag.endswith("}row")):
                values: list[str] = []
                for cell in (node for node in row if node.tag.endswith("}c")):
                    value_node = next(
                        (
                            node
                            for node in cell.iter()
                            if node.tag.endswith(("}v", "}t"))
                        ),
                        None,
                    )
                    value = value_node.text if value_node is not None else ""
                    if cell.attrib.get("t") == "s" and value and value.isdigit():
                        shared_index = int(value)
                        value = (
                            shared_strings[shared_index]
                            if shared_index < len(shared_strings)
                            else value
                        )
                    values.append(value or "")
                if any(values):
                    rows.append("\t".join(values))
            if rows:
                display_name = display_name_by_path.get(sheet_path) or (
                    display_names[index - 1]
                    if index <= len(display_names)
                    else f"Sheet {index}"
                )
                output.append(
                    ParsedSection(
                        content="\n".join(rows),
                        heading_path=(display_name,),
                        metadata={
                            "sheet_name": display_name,
                            "sheet_index": index,
                        },
                    )
                )
        return output


def _xlsx_sheet_names(archive: ZipFile) -> list[str]:
    if "xl/workbook.xml" not in archive.namelist():
        return []
    try:
        root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    except ElementTree.ParseError:
        return []
    return [
        str(node.attrib.get("name") or "").strip()
        for node in root.iter()
        if node.tag.endswith("}sheet") and str(node.attrib.get("name") or "").strip()
    ]


def _xlsx_shared_strings(data: bytes) -> list[str]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise FileProcessingError("Invalid XLSX shared strings XML") from exc
    return [
        "".join(child.text or "" for child in node.iter() if child.tag.endswith("}t"))
        for node in root.iter()
        if node.tag.endswith("}si")
    ]


def _xlsx_sheet_name_map(archive: ZipFile) -> dict[str, str]:
    workbook_path = "xl/workbook.xml"
    relationships_path = "xl/_rels/workbook.xml.rels"
    if not {
        workbook_path,
        relationships_path,
    }.issubset(archive.namelist()):
        return {}
    try:
        workbook = ElementTree.fromstring(archive.read(workbook_path))
        relationships = ElementTree.fromstring(archive.read(relationships_path))
    except ElementTree.ParseError:
        return {}
    targets = {
        str(node.attrib.get("Id") or ""): str(node.attrib.get("Target") or "")
        for node in relationships.iter()
        if node.tag.endswith("}Relationship")
    }
    output: dict[str, str] = {}
    for sheet in (node for node in workbook.iter() if node.tag.endswith("}sheet")):
        name = str(sheet.attrib.get("name") or "").strip()
        relationship_id = next(
            (value for key, value in sheet.attrib.items() if key.endswith("}id")),
            "",
        )
        target = targets.get(relationship_id, "").lstrip("/")
        if target.startswith("xl/"):
            path = target
        else:
            path = f"xl/{target.lstrip('./')}"
        if name and target:
            output[path] = name
    return output


def _extract_pdf(data: bytes, _: str) -> str:
    return "\n\n".join(section.content for section in _extract_pdf_sections(data))


def _extract_pdf_sections(data: bytes) -> list[ParsedSection]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise UnsupportedFileTypeError(
            "PDF extraction requires the optional 'pypdf' package or an injected '.pdf' extractor"
        ) from exc
    return [
        ParsedSection(
            content=page.extract_text() or "",
            element_id=f"page_{page_number:03d}",
            page_number=page_number,
            metadata={"page_number": page_number},
        )
        for page_number, page in enumerate(PdfReader(BytesIO(data)).pages, 1)
    ]


def _normalise_text(value: str) -> str:
    value = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[\t ]+", " ", line).strip() for line in value.split("\n")]
    output: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        output.append(line)
        previous_blank = is_blank
    return "\n".join(output).strip()


__all__ = [
    "DEFAULT_MAX_FILE_BYTES",
    "FileProcessingError",
    "FileProcessor",
    "FileSizeLimitError",
    "FileTextLimitError",
    "FinxFileExtensions",
    "FinxMimeTypes",
    "ParsedDocument",
    "ParsedSection",
    "ProcessedFile",
    "UnsupportedFileTypeError",
    "extract_file_text",
]
