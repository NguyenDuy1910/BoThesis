"""The script executed inside the artifact sandbox container.

It is copied into ``/workspace/context`` on every run — together with the
capability modules under ``context/skills/`` — and executed with the sandbox
image's own Python, so it must stay standalone: no BoThesis imports, standard
library only. Document-format knowledge lives in the skills (``skills/docx.py``
turns Word documents into Markdown, ``skills/pdf.py`` renders Markdown to
PDF); this runner only parses the request, dispatches the operation, selects
the skill a file format calls for, and reports the outcome. Every outcome —
success or failure — is written to ``output/result.json``; nothing is raised
out of ``main``.

Operations are deliberately fixed and small. The model chooses one and its
arguments; it never supplies code or shell commands, and it never selects a
skill — the source file's format does, deterministically.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

INPUT_DIRECTORY = "input"
CONTEXT_DIRECTORY = "context"
OUTPUT_DIRECTORY = "output"
SKILLS_DIRECTORY = "skills"
REQUEST_FILE_NAME = "request.json"
RESULT_FILE_NAME = "result.json"
DEFAULT_DOCUMENT_NAME = "document.md"
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".text"})
MARKDOWN_CONTENT_TYPE = "text/markdown"
PDF_SUFFIX = ".pdf"
PDF_CONTENT_TYPE = "application/pdf"
# Source formats that convert to Markdown via a skill, keyed by file suffix.
# PDF is not here: it keeps its own strategy (preserve a fillable form,
# extract a flat document) inside _import_pdf.
IMPORT_SKILLS: dict[str, str] = {".docx": "docx"}
MAX_EDITS = 50
MAX_FILE_NAME_LENGTH = 240
MAX_FILL_FIELDS = 200
MAX_CONTEXT_FIELDS = 200
MAX_CONTEXT_TEXT_CHARACTERS = 40_000


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


def import_document(workspace: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Turn a source document (a template, form, or any other file) into
    an editable Markdown document, converting via the format's skill."""

    source_name = _file_name(arguments.get("file_name"))
    target_name = _file_name(arguments.get("target_file_name") or DEFAULT_DOCUMENT_NAME)
    source = workspace / INPUT_DIRECTORY / source_name
    if not source.is_file():
        raise OperationError(f"source file is missing: {source_name}")
    suffix = source.suffix.casefold()
    if suffix == PDF_SUFFIX:
        return _import_pdf(workspace, source, target_name)
    if suffix in MARKDOWN_SUFFIXES:
        text = source.read_bytes().decode("utf-8", errors="replace")
    elif suffix in IMPORT_SKILLS:
        skill = _load_skill(IMPORT_SKILLS[suffix])
        try:
            text = skill.to_markdown(source)
        except ValueError as exc:
            raise OperationError(str(exc)) from exc
    else:
        supported = ", ".join(
            sorted(MARKDOWN_SUFFIXES | set(IMPORT_SKILLS) | {PDF_SUFFIX})
        )
        raise OperationError(
            f"unsupported source format: {suffix or 'no extension'} "
            f"(supported: {supported})"
        )
    if not text.strip():
        raise OperationError("the source has no readable text content")
    return {
        **_write_output(workspace, target_name, _normalized(text)),
        "content_type": MARKDOWN_CONTENT_TYPE,
        "source_format": suffix.lstrip("."),
    }


def _import_pdf(workspace: Path, source: Path, target_name: str) -> dict[str, Any]:
    """Choose the PDF strategy from the document itself.

    A fillable form keeps the original PDF as the artifact — layout intact,
    values set later through ``fill_pdf`` — described to the caller by a
    context file. A flat PDF is extracted to editable Markdown. A scanned PDF
    with neither fields nor text is reported, not guessed at.
    """

    skill = _load_skill("pdf")
    try:
        description = skill.inspect(source)
    except ValueError as exc:
        raise OperationError(str(exc)) from exc
    fields = list(description.get("fields") or [])
    text = str(description.get("text") or "")
    stem = Path(target_name).stem or "document"
    if fields:
        artifact_name = f"{stem}{PDF_SUFFIX}"
        data = source.read_bytes()
        (workspace / OUTPUT_DIRECTORY / artifact_name).write_bytes(data)
        context_name = _write_form_context(workspace, artifact_name, fields, text)
        return {
            "file_name": artifact_name,
            "size_bytes": len(data),
            "content_type": PDF_CONTENT_TYPE,
            "artifact_kind": "pdf_form",
            "context_file_name": context_name,
            "field_count": len(fields),
            "source_format": "pdf",
        }
    if not text.strip():
        raise OperationError(
            "the PDF has no fillable form fields and no extractable text "
            "(it may be scanned images), so it cannot be imported"
        )
    return {
        **_write_output(workspace, f"{stem}.md", _normalized(text)),
        "content_type": MARKDOWN_CONTENT_TYPE,
        "source_format": "pdf",
    }


def fill_pdf(workspace: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Set form field values on the input PDF, preserving its layout."""

    file_name = _file_name(arguments.get("file_name"))
    raw_fields = arguments.get("fields")
    if not isinstance(raw_fields, Mapping) or not raw_fields:
        raise OperationError("fields must be a non-empty object of field names to values")
    if len(raw_fields) > MAX_FILL_FIELDS:
        raise OperationError(f"at most {MAX_FILL_FIELDS} fields are accepted per revision")
    values: dict[str, str] = {}
    for name, value in raw_fields.items():
        if not isinstance(name, str) or not name.strip():
            raise OperationError("field names must be non-empty text")
        if not isinstance(value, str):
            raise OperationError(f"field {name!r}: the value must be text")
        values[name] = value
    source = workspace / INPUT_DIRECTORY / file_name
    if not source.is_file():
        raise OperationError(f"input file is missing: {file_name}")
    skill = _load_skill("pdf")
    target = workspace / OUTPUT_DIRECTORY / file_name
    try:
        applied = skill.fill(source, values, target)
        description = skill.inspect(target)
    except ValueError as exc:
        raise OperationError(str(exc)) from exc
    context_name = _write_form_context(
        workspace,
        file_name,
        list(description.get("fields") or []),
        str(description.get("text") or ""),
    )
    return {
        "file_name": file_name,
        "size_bytes": target.stat().st_size,
        "content_type": PDF_CONTENT_TYPE,
        "artifact_kind": "pdf_form",
        "context_file_name": context_name,
        "applied": applied,
    }


def _write_form_context(
    workspace: Path,
    artifact_name: str,
    fields: list[Any],
    text: str,
) -> str:
    """Write the model-facing description of a fillable PDF artifact."""

    context_name = f"{artifact_name}.context.md"
    lines = [
        f"# {artifact_name} — fillable PDF form",
        "",
        "This document is the original PDF; its layout is preserved. Change it",
        'by calling artifact_edit with "fields" entries that map the exact',
        "field names below to their new values. A button or choice field only",
        "accepts one of its listed states.",
        "",
        "## Form fields",
    ]
    for field in fields[:MAX_CONTEXT_FIELDS]:
        if not isinstance(field, Mapping):
            continue
        line = (
            f'- name: "{field.get("name", "")}" | type: {field.get("type", "text")}'
            f' | value: "{field.get("value", "")}"'
        )
        states = field.get("states")
        if states:
            line += " | states: " + ", ".join(f'"{state}"' for state in states)
        lines.append(line)
    if len(fields) > MAX_CONTEXT_FIELDS:
        lines.append(f"… and {len(fields) - MAX_CONTEXT_FIELDS} more fields")
    lines.extend(("", "## Document text", ""))
    if len(text) > MAX_CONTEXT_TEXT_CHARACTERS:
        text = f"{text[:MAX_CONTEXT_TEXT_CHARACTERS].rstrip()}\n…[text truncated]…"
    lines.append(text)
    (workspace / OUTPUT_DIRECTORY / context_name).write_text(
        "\n".join(lines), "utf-8"
    )
    return context_name


def export_pdf(workspace: Path, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Render the Markdown input document to a PDF via the PDF skill."""

    file_name = _file_name(arguments.get("file_name"))
    title = arguments.get("title")
    text = _read_input_text(workspace, file_name)
    target_name = f"{Path(file_name).stem}.pdf"
    target = workspace / OUTPUT_DIRECTORY / target_name
    skill = _load_skill("pdf")
    try:
        skill.export(
            text,
            title=str(title) if isinstance(title, str) and title else Path(file_name).stem,
            target=target,
        )
    except ValueError as exc:
        raise OperationError(str(exc)) from exc
    return {"file_name": target_name, "size_bytes": target.stat().st_size}


OPERATIONS: dict[str, Callable[[Path, Mapping[str, Any]], dict[str, Any]]] = {
    "write": write,
    "replace": replace,
    "import": import_document,
    "fill_pdf": fill_pdf,
    "export_pdf": export_pdf,
}


# --- Skills ----------------------------------------------------------------

_SKILL_CACHE: dict[str, Any] = {}


def _load_skill(name: str) -> Any:
    """Load one capability module shipped next to this runner.

    Skills live in ``skills/`` beside this file — ``/workspace/context/skills``
    inside the container — and are plain standalone modules, so they are
    loaded by file path rather than through ``sys.path``.
    """

    module = _SKILL_CACHE.get(name)
    if module is None:
        path = Path(__file__).resolve().parent / SKILLS_DIRECTORY / f"{name}.py"
        spec = (
            importlib.util.spec_from_file_location(f"bothesis_sandbox_skill_{name}", path)
            if path.is_file()
            else None
        )
        if spec is None or spec.loader is None:
            raise OperationError(f"skill is not available: {name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SKILL_CACHE[name] = module
    return module


# --- Helpers ---------------------------------------------------------------


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
