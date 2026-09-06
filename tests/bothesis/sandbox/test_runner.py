"""The in-container runner, exercised directly on a temporary workspace."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from bothesis.sandbox import runner


def run(workspace: Path, operation: str, arguments: dict[str, Any], files: dict[str, bytes] | None = None) -> tuple[int, dict[str, Any]]:
    for directory in ("input", "context", "work", "output"):
        (workspace / directory).mkdir(parents=True, exist_ok=True)
    for name, data in (files or {}).items():
        (workspace / "input" / name).write_bytes(data)
    (workspace / "context" / "request.json").write_text(
        json.dumps({"operation": operation, "arguments": arguments}), "utf-8"
    )
    exit_code = runner.main(["runner.py", str(workspace)])
    result = json.loads((workspace / "output" / "result.json").read_text("utf-8"))
    return exit_code, result


def test_write_normalizes_line_endings_and_reports_the_file(tmp_path: Path) -> None:
    exit_code, result = run(
        tmp_path, "write", {"file_name": "memo.md", "content": "# Memo\r\n\r\nHello\r\n\r\n"}
    )

    assert exit_code == 0
    assert result["status"] == "ok"
    assert result["file_name"] == "memo.md"
    assert (tmp_path / "output" / "memo.md").read_text("utf-8") == "# Memo\n\nHello\n"


def test_replace_applies_unique_edits_atomically(tmp_path: Path) -> None:
    original = b"Date: 2026-09-01\n\nSigned: Alice\n"
    exit_code, result = run(
        tmp_path,
        "replace",
        {
            "file_name": "memo.md",
            "edits": [
                {"find": "2026-09-01", "replace": "2026-09-06"},
                {"find": "Signed: Alice", "replace": "Signed: Bob"},
            ],
        },
        {"memo.md": original},
    )

    assert exit_code == 0
    assert result["applied"] == 2
    assert (tmp_path / "output" / "memo.md").read_bytes() == b"Date: 2026-09-06\n\nSigned: Bob\n"


@pytest.mark.parametrize(
    ("edits", "expected"),
    [
        ([{"find": "missing", "replace": "x"}], "text not found"),
        ([{"find": "the", "replace": "a"}], "matches 2 times"),
        ([{"find": "", "replace": "a"}], "find must be non-empty"),
    ],
)
def test_replace_refuses_missing_ambiguous_or_empty_matches(
    tmp_path: Path, edits: list[dict[str, str]], expected: str
) -> None:
    exit_code, result = run(
        tmp_path,
        "replace",
        {"file_name": "memo.md", "edits": edits},
        {"memo.md": b"the cat and the dog\n"},
    )

    assert exit_code == 1
    assert result["status"] == "error"
    assert expected in result["error"]
    # An atomic failure produces no document.
    assert not (tmp_path / "output" / "memo.md").exists()


def test_import_copies_markdown_templates(tmp_path: Path) -> None:
    exit_code, result = run(
        tmp_path,
        "import",
        {"file_name": "template.md", "target_file_name": "nda.md"},
        {"template.md": b"# NDA\n\nBetween [A] and [B].\n"},
    )

    assert exit_code == 0
    assert result["source_format"] == "md"
    assert (tmp_path / "output" / "nda.md").read_text("utf-8") == "# NDA\n\nBetween [A] and [B].\n"


def test_import_converts_docx_headings_paragraphs_and_tables(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("NDA Template", 1)
    document.add_paragraph("Between [Party A] and [Party B].")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Term"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Duration"
    table.cell(1, 1).text = "[years]"
    buffer = io.BytesIO()
    document.save(buffer)

    exit_code, result = run(
        tmp_path,
        "import",
        {"file_name": "nda.docx", "target_file_name": "nda.md"},
        {"nda.docx": buffer.getvalue()},
    )

    assert exit_code == 0, result
    assert result["source_format"] == "docx"
    assert (tmp_path / "output" / "nda.md").read_text("utf-8") == (
        "# NDA Template\n\nBetween [Party A] and [Party B].\n\n"
        "| Term | Value |\n| --- | --- |\n| Duration | [years] |\n"
    )


def test_import_rejects_formats_the_runner_cannot_read(tmp_path: Path) -> None:
    exit_code, result = run(
        tmp_path, "import", {"file_name": "slides.pptx"}, {"slides.pptx": b"binary"}
    )

    assert exit_code == 1
    assert "unsupported template format: .pptx" in result["error"]


def test_export_pdf_renders_or_names_the_missing_libraries(tmp_path: Path) -> None:
    exit_code, result = run(
        tmp_path,
        "export_pdf",
        {"file_name": "memo.md", "title": "Memo"},
        {"memo.md": b"# Memo\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"},
    )

    try:
        import markdown  # noqa: F401
        from xhtml2pdf import pisa  # noqa: F401
    except ImportError:
        assert exit_code == 1
        assert "xhtml2pdf" in result["error"]
        return
    assert exit_code == 0, result
    assert (tmp_path / "output" / "memo.pdf").read_bytes().startswith(b"%PDF-")


def test_unknown_operations_and_bad_file_names_are_reported_not_raised(tmp_path: Path) -> None:
    exit_code, result = run(tmp_path, "shell", {"command": "rm -rf /"})
    assert exit_code == 1
    assert "unsupported operation" in result["error"]

    exit_code, result = run(tmp_path, "write", {"file_name": "../escape.md", "content": "x"})
    assert exit_code == 1
    assert "file_name is invalid" in result["error"]
