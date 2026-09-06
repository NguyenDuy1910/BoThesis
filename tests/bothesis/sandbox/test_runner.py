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


def test_import_copies_markdown_documents(tmp_path: Path) -> None:
    exit_code, result = run(
        tmp_path,
        "import",
        {"file_name": "source.md", "target_file_name": "nda.md"},
        {"source.md": b"# NDA\n\nBetween [A] and [B].\n"},
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
    assert "unsupported source format: .pptx" in result["error"]


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


# --- PDF fixtures -----------------------------------------------------------
#
# Minimal but valid PDFs, assembled byte by byte so the tests need no PDF
# writer: a page with one text line, optionally carrying one AcroForm text
# field named "ho_ten".


def _pdf_bytes(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _content_stream(text: str) -> bytes:
    content = f"BT /Helv 12 Tf 72 720 Td ({text}) Tj ET".encode()
    return b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content)


_FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def form_pdf() -> bytes:
    """One page, the label "Ho ten:", and one empty AcroForm text field."""

    return _pdf_bytes(
        [
            b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [4 0 R] "
            b"/DA (/Helv 0 Tf 0 g) /NeedAppearances true >> >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Annots [4 0 R] /Contents 5 0 R "
            b"/Resources << /Font << /Helv 6 0 R >> >> >>",
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (ho_ten) /V () "
            b"/Rect [150 710 400 730] /DA (/Helv 12 Tf 0 g) >>",
            _content_stream("Ho ten:"),
            _FONT,
        ]
    )


def flat_pdf(text: str = "Quy dinh nghi phep nam 2026") -> bytes:
    """One page of plain text: no AcroForm, extractable content."""

    return _pdf_bytes(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /Helv 5 0 R >> >> >>",
            _content_stream(text),
            _FONT,
        ]
    )


def blank_pdf() -> bytes:
    """One empty page: no fields, no text — the scanned-image shape."""

    return _pdf_bytes(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
        ]
    )


def test_import_keeps_a_fillable_pdf_and_describes_its_fields(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    original = form_pdf()
    exit_code, result = run(
        tmp_path,
        "import",
        {"file_name": "don-mien-thi.pdf", "target_file_name": "don-mien-thi.md"},
        {"don-mien-thi.pdf": original},
    )

    assert exit_code == 0, result
    assert result["file_name"] == "don-mien-thi.pdf"
    assert result["content_type"] == "application/pdf"
    assert result["artifact_kind"] == "pdf_form"
    assert result["field_count"] == 1
    # The artifact is the original PDF, byte for byte: layout preserved.
    assert (tmp_path / "output" / "don-mien-thi.pdf").read_bytes() == original
    context = (tmp_path / "output" / result["context_file_name"]).read_text("utf-8")
    assert 'name: "ho_ten"' in context
    assert "Ho ten:" in context


def test_import_extracts_a_flat_pdf_to_editable_markdown(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    exit_code, result = run(
        tmp_path,
        "import",
        {"file_name": "policy.pdf", "target_file_name": "policy.md"},
        {"policy.pdf": flat_pdf()},
    )

    assert exit_code == 0, result
    assert result["file_name"] == "policy.md"
    assert result["content_type"] == "text/markdown"
    assert result["source_format"] == "pdf"
    text = (tmp_path / "output" / "policy.md").read_text("utf-8")
    assert "Quy dinh nghi phep nam 2026" in text


def test_import_reports_a_scanned_pdf_instead_of_guessing(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    exit_code, result = run(
        tmp_path,
        "import",
        {"file_name": "scan.pdf", "target_file_name": "scan.md"},
        {"scan.pdf": blank_pdf()},
    )

    assert exit_code == 1
    assert "no fillable form fields and no extractable text" in result["error"]


def test_fill_pdf_sets_field_values_and_refreshes_the_description(tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    exit_code, result = run(
        tmp_path,
        "fill_pdf",
        {"file_name": "don.pdf", "fields": {"ho_ten": "Trần Văn A"}},
        {"don.pdf": form_pdf()},
    )

    assert exit_code == 0, result
    assert result["applied"] == 1
    assert result["content_type"] == "application/pdf"
    reader = pypdf.PdfReader(str(tmp_path / "output" / "don.pdf"))
    assert reader.get_fields()["ho_ten"].value == "Trần Văn A"
    context = (tmp_path / "output" / result["context_file_name"]).read_text("utf-8")
    assert "Trần Văn A" in context


def test_fill_pdf_rejects_unknown_fields_naming_the_real_ones(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    exit_code, result = run(
        tmp_path,
        "fill_pdf",
        {"file_name": "don.pdf", "fields": {"full_name": "A"}},
        {"don.pdf": form_pdf()},
    )

    assert exit_code == 1
    assert "unknown form fields: full_name" in result["error"]
    assert "ho_ten" in result["error"]
    assert not (tmp_path / "output" / "don.pdf").exists()
