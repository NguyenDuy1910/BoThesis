"""DOCX skill: turn a Word document into editable Markdown.

Executed inside the sandbox container, loaded by ``runner.py`` from
``context/skills/``. It must stay standalone: standard library plus the
optional ``python-docx`` package the sandbox image installs. Failures are
raised as ``ValueError`` with user-safe messages; the runner reports them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SUFFIXES = (".docx",)


def to_markdown(path: Path) -> str:
    """Convert one DOCX file to Markdown, keeping tables in document order."""

    try:
        import docx  # type: ignore[import-not-found]
        from docx.table import Table  # type: ignore[import-not-found]
        from docx.text.paragraph import Paragraph  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError(
            "DOCX source documents need the python-docx package in the sandbox image"
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
