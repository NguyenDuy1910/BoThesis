"""The script executed inside the artifact sandbox container.

It is copied into ``/workspace/context`` on every run and executed with the
sandbox image's own Python, so it must stay standalone: no BoThesis imports,
standard library only, plus the optional document libraries the image installs
(``python-docx`` for DOCX templates, ``markdown`` and ``xhtml2pdf`` for PDF
export). Every outcome — success or failure — is written to
``output/result.json``; nothing is raised out of ``main``.

Operations are deliberately fixed and small. The model chooses one and its
arguments; it never supplies code or shell commands.
"""

from __future__ import annotations

import html
import io
import json
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

INPUT_DIRECTORY = "input"
CONTEXT_DIRECTORY = "context"
OUTPUT_DIRECTORY = "output"
REQUEST_FILE_NAME = "request.json"
RESULT_FILE_NAME = "result.json"
DEFAULT_DOCUMENT_NAME = "document.md"
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".text"})
MAX_EDITS = 50
MAX_FILE_NAME_LENGTH = 240


class OperationError(ValueError):
    """An operation could not be applied; the message is user-safe."""


def main(argv: list[str]) -> int:
    workspace = Path(argv[1] if len(argv) > 1 else "/workspace")
    output = workspace / OUTPUT_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any]
    try:
        request = json.loads(
            (workspace / CONTEXT_DIRECTORY / REQUEST_FILE_NAME).read_text("utf-8")
        )
        operation = request.get("operation")
        arguments = request.get("arguments") or {}
        handler = OPERATIONS.get(operation)
        if handler is None:
            raise OperationError(f"unsupported operation: {operation!r}")
        if not isinstance(arguments, Mapping):
            raise OperationError("operation arguments must be an object")
        result = {"status": "ok", "operation": operation, **handler(workspace, arguments)}
    except OperationError as exc:
        result = {"status": "error", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - every failure is a reported result
        result = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    (output / RESULT_FILE_NAME).write_text(json.dumps(result), "utf-8")
    return 0 if result["status"] == "ok" else 1


# --- Operations -----------------------------------------------------------


def write(workspace: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Write a complete document from the supplied text."""

    file_name = _file_name(arguments.get("file_name"))
    content = arguments.get("content")
    if not isinstance(content, str) or not content.strip():
        raise OperationError("content must be non-empty text")
    return _write_output(workspace, file_name, _normalized(content))


def replace(workspace: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Apply exact find/replace edits to the input document, atomically.

    Every ``find`` must occur exactly once so an edit can never land in the
    wrong place: a missing or ambiguous match fails the whole operation and
    the message tells the caller which text to make more specific.
    """

    file_name = _file_name(arguments.get("file_name"))
    edits = arguments.get("edits")
    if not isinstance(edits, list) or not edits:
        raise OperationError("edits must be a non-empty list")
    if len(edits) > MAX_EDITS:
        raise OperationError(f"at most {MAX_EDITS} edits are accepted per revision")
    content = _read_input_text(workspace, file_name)
    problems: list[str] = []
    for position, edit in enumerate(edits, start=1):
        if not isinstance(edit, Mapping):
            raise OperationError(f"edit {position} must be an object")
        find = edit.get("find")
        replacement = edit.get("replace")
        if not isinstance(find, str) or not find:
            raise OperationError(f"edit {position}: find must be non-empty text")
        if not isinstance(replacement, str):
            raise OperationError(f"edit {position}: replace must be text")
        occurrences = content.count(find)
        if occurrences == 0:
            problems.append(f"edit {position}: text not found: {_preview(find)}")
            continue
        if occurrences > 1:
            problems.append(
                f"edit {position}: text matches {occurrences} times, include more "
                f"surrounding text: {_preview(find)}"
            )
            continue
        content = content.replace(find, replacement, 1)
    if problems:
        raise OperationError("; ".join(problems))
    if not content.strip():
        raise OperationError("the edits would leave the document empty")
    return {**_write_output(workspace, file_name, _normalized(content)), "applied": len(edits)}


def import_template(workspace: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Turn a Knowledge Base template file into an editable Markdown document."""

    source_name = _file_name(arguments.get("file_name"))
    target_name = _file_name(arguments.get("target_file_name") or DEFAULT_DOCUMENT_NAME)
    source = workspace / INPUT_DIRECTORY / source_name
    if not source.is_file():
        raise OperationError(f"template file is missing: {source_name}")
    suffix = source.suffix.casefold()
    if suffix in MARKDOWN_SUFFIXES:
        text = source.read_bytes().decode("utf-8", errors="replace")
    elif suffix == ".docx":
        text = _docx_to_markdown(source)
    else:
        raise OperationError(
            f"unsupported template format: {suffix or 'no extension'} "
            "(supported: .md, .markdown, .txt, .docx)"
        )
    if not text.strip():
        raise OperationError("the template has no readable text content")
    return {
        **_write_output(workspace, target_name, _normalized(text)),
        "source_format": suffix.lstrip("."),
    }


def export_pdf(workspace: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Render the Markdown input document to a PDF."""

    file_name = _file_name(arguments.get("file_name"))
    title = arguments.get("title")
    text = _read_input_text(workspace, file_name)
    try:
        import markdown  # type: ignore[import-not-found]
        from xhtml2pdf import pisa  # type: ignore[import-not-found]
    except ImportError as exc:
        raise OperationError(
            "PDF export needs the markdown and xhtml2pdf packages in the sandbox image"
        ) from exc
    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "sane_lists"], output_format="html"
    )
    document_title = html.escape(str(title) if isinstance(title, str) and title else Path(file_name).stem)
    page = (
        "<html><head><meta charset='utf-8'>"
        f"<title>{document_title}</title><style>{_PDF_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )
    target_name = f"{Path(file_name).stem}.pdf"
    target = workspace / OUTPUT_DIRECTORY / target_name
    with target.open("wb") as handle:
        status = pisa.CreatePDF(io.StringIO(page), dest=handle, encoding="utf-8")
    if getattr(status, "err", 0):
        raise OperationError("PDF rendering failed")
    return {"file_name": target_name, "size_bytes": target.stat().st_size}


OPERATIONS: dict[str, Callable[[Path, Mapping[str, Any]], dict[str, Any]]] = {
    "write": write,
    "replace": replace,
    "import": import_template,
    "export_pdf": export_pdf,
}


# --- DOCX ------------------------------------------------------------------


def _docx_to_markdown(path: Path) -> str:
    try:
        import docx  # type: ignore[import-not-found]
        from docx.table import Table  # type: ignore[import-not-found]
        from docx.text.paragraph import Paragraph  # type: ignore[import-not-found]
    except ImportError as exc:
        raise OperationError(
            "DOCX templates need the python-docx package in the sandbox image"
        ) from exc
    document = docx.Document(str(path))
    lines: list[str] = []
    # Walk the body in order so tables keep their place between paragraphs.
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append(_paragraph_markdown(Paragraph(child, document)))
        elif tag == "tbl":
            lines.extend(_table_markdown(Table(child, document)))
            lines.append("")
    return "\n".join(lines)


def _paragraph_markdown(paragraph: Any) -> str:
    text = " ".join(paragraph.text.split())
    style = ""
    if paragraph.style is not None and paragraph.style.name:
        style = str(paragraph.style.name)
    if not text:
        return ""
    heading = re.fullmatch(r"Heading (\d)", style)
    if heading:
        return f"{'#' * int(heading.group(1))} {text}\n"
    if style == "Title":
        return f"# {text}\n"
    if "List" in style:
        return f"- {text}"
    return f"{text}\n"


def _table_markdown(table: Any) -> list[str]:
    rows = [
        [" ".join(cell.text.split()).replace("|", "\\|") for cell in row.cells]
        for row in table.rows
    ]
    if not rows:
        return []
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        "| " + " | ".join(rows[0]) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return lines


# --- Helpers ---------------------------------------------------------------

_PDF_STYLE = (
    "@page { size: A4; margin: 2cm; }"
    "body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.4; }"
    "h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }"
    "table { border-collapse: collapse; width: 100%; margin: 8pt 0; }"
    "th, td { border: 1px solid #999; padding: 4pt 6pt; text-align: left; }"
    "code, pre { font-family: Courier, monospace; font-size: 9.5pt; }"
    "blockquote { border-left: 3px solid #bbb; margin: 8pt 0; padding-left: 8pt; color: #444; }"
)


def _file_name(value: object) -> str:
    if not isinstance(value, str):
        raise OperationError("file_name must be text")
    name = value.strip()
    if (
        not name
        or len(name) > MAX_FILE_NAME_LENGTH
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise OperationError("file_name is invalid")
    return name


def _read_input_text(workspace: Path, file_name: str) -> str:
    source = workspace / INPUT_DIRECTORY / file_name
    if not source.is_file():
        raise OperationError(f"input file is missing: {file_name}")
    return source.read_bytes().decode("utf-8", errors="replace")


def _write_output(workspace: Path, file_name: str, text: str) -> dict[str, Any]:
    data = text.encode("utf-8")
    (workspace / OUTPUT_DIRECTORY / file_name).write_bytes(data)
    return {"file_name": file_name, "size_bytes": len(data), "characters": len(text)}


def _normalized(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return f"{normalized}\n"


def _preview(text: str, limit: int = 80) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return repr(collapsed)
    return repr(f"{collapsed[: limit - 1]}…")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
