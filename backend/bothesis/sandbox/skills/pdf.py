"""PDF skill: inspect and fill PDF forms, and render Markdown to PDF.

Executed inside the sandbox container, loaded by ``runner.py`` from
``context/skills/``. It must stay standalone: standard library plus the
optional packages the sandbox image installs (``pypdf`` for form fields and
text extraction, ``markdown`` and ``xhtml2pdf`` for the Markdown export).
Failures are raised as ``ValueError`` with user-safe messages; the runner
reports them.
"""

from __future__ import annotations

import html
import io
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_STYLE = (
    "@page { size: A4; margin: 2cm; }"
    "body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.4; }"
    "h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }"
    "table { border-collapse: collapse; width: 100%; margin: 8pt 0; }"
    "th, td { border: 1px solid #999; padding: 4pt 6pt; text-align: left; }"
    "code, pre { font-family: Courier, monospace; font-size: 9.5pt; }"
    "blockquote { border-left: 3px solid #bbb; margin: 8pt 0; padding-left: 8pt; color: #444; }"
)


_FIELD_TYPES = {
    "/Tx": "text",
    "/Btn": "button",
    "/Ch": "choice",
    "/Sig": "signature",
}


def inspect(path: Path) -> dict[str, Any]:
    """Describe a PDF: its fillable AcroForm fields and its extracted text.

    ``fields`` is empty for a flat (non-fillable) PDF; ``text`` is empty for a
    scanned one. The caller decides the import strategy from both.
    """

    reader = _reader(path)
    fields: list[dict[str, Any]] = []
    for name, field in (reader.get_fields() or {}).items():
        entry: dict[str, Any] = {
            "name": str(name),
            "type": _FIELD_TYPES.get(str(field.field_type or ""), "text"),
            "value": "" if field.value is None else str(field.value),
        }
        states = field.get("/_States_")
        if states:
            # A button or choice accepts only these values (e.g. "/Yes", "/Off").
            entry["states"] = [str(state) for state in states]
        fields.append(entry)
    text = "\n\n".join(
        stripped
        for page in reader.pages
        if (stripped := (page.extract_text() or "").strip())
    )
    return {"fields": fields, "text": text}


def fill(path: Path, values: Mapping[str, str], target: Path) -> int:
    """Set AcroForm field values on a copy of the PDF, preserving its layout.

    Every name must exist in the form; an unknown name fails the whole
    operation and the message lists the fields that do exist, so the caller
    can correct itself. Returns the number of fields written.
    """

    pypdf = _pypdf()
    reader = _reader(path)
    available = {str(name) for name in (reader.get_fields() or {})}
    if not available:
        raise ValueError("the PDF has no fillable form fields")
    unknown = sorted(set(values) - available)
    if unknown:
        raise ValueError(
            "unknown form fields: " + ", ".join(unknown)
            + "; the form's fields are: " + ", ".join(sorted(available))
        )
    writer = pypdf.PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        if page.get("/Annots"):
            # auto_regenerate=False sets NeedAppearances so viewers render
            # the new values without pre-built appearance streams.
            writer.update_page_form_field_values(
                page, dict(values), auto_regenerate=False
            )
    with target.open("wb") as handle:
        writer.write(handle)
    return len(values)


def _reader(path: Path) -> Any:
    pypdf = _pypdf()
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - unreadable input is a user-safe outcome
        raise ValueError("the PDF could not be read (it may be corrupted)") from exc
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise ValueError("the PDF is password-protected") from exc
    return reader


def _pypdf() -> Any:
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError(
            "PDF processing needs the pypdf package in the sandbox image"
        ) from exc
    return pypdf


def export(text: str, *, title: str, target: Path) -> None:
    """Render Markdown ``text`` as a PDF written to ``target``."""

    try:
        import markdown  # type: ignore[import-not-found]
        from xhtml2pdf import pisa  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError(
            "PDF export needs the markdown and xhtml2pdf packages in the sandbox image"
        ) from exc
    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "sane_lists"], output_format="html"
    )
    page = (
        "<html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )
    with target.open("wb") as handle:
        status = pisa.CreatePDF(io.StringIO(page), dest=handle, encoding="utf-8")
    if getattr(status, "err", 0):
        raise ValueError("PDF rendering failed")
