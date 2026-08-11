from __future__ import annotations

import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from bothesis.connector.file.file_connector import (
    MANUAL_UPLOAD_SCOPE_VALUE,
    LocalFileConnector,
    ManualFileUploadConnector,
)
from bothesis.connector.file.processing import FileProcessor, UnsupportedFileTypeError
from bothesis.connector.models import ConnectorScope, SourceCheckpoint


def test_file_processor_extracts_text_json_and_docx() -> None:
    processor = FileProcessor()

    text = processor.process_bytes(b"alpha\r\n\r\nbeta", file_name="notes.txt")
    assert text.text == "alpha\n\nbeta"
    assert text.sha256 == hashlib.sha256(b"alpha\r\n\r\nbeta").hexdigest()

    structured = processor.process_bytes(b'{"name":"BoThesis"}', file_name="data.json")
    assert '"name": "BoThesis"' in structured.text

    archive_data = BytesIO()
    with ZipFile(archive_data, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>Hello</w:t></w:r>'
            '<w:r><w:t>world</w:t></w:r></w:p></w:body></w:document>',
        )
    document = processor.process_bytes(archive_data.getvalue(), file_name="brief.docx")
    assert document.text == "Hello world"


def test_file_processor_rejects_unsupported_formats() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        FileProcessor().process_bytes(b"legacy", file_name="legacy.doc")


@pytest.mark.asyncio
async def test_manual_upload_discovers_incrementally_and_preserves_acl(tmp_path) -> None:
    file_path = tmp_path / "policy.txt"
    file_path.write_text("Enterprise policy", encoding="utf-8")
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    record_path = tmp_path / "upload-1.json"
    record_path.write_text(
        json.dumps(
            {
                "external_id": "upload-1",
                "path": "policy.txt",
                "file_name": "Policy.txt",
                "sha256": digest,
                "size_bytes": file_path.stat().st_size,
                "uploaded_at": "2026-08-10T01:00:00Z",
                "acl": {
                    "user_emails": ["Owner@Example.com"],
                    "user_group_ids": ["Finance"],
                    "is_public": False,
                },
                "metadata": {"domains": ["finance", "policy"]},
            }
        ),
        encoding="utf-8",
    )
    connector = ManualFileUploadConnector({"base_dir": str(tmp_path)})
    scope = ConnectorScope(
        scope_type="folder",
        scope_value=MANUAL_UPLOAD_SCOPE_VALUE,
        display_name="Manual uploads",
    )

    changes = await connector.discover_changes(SourceCheckpoint(), scope)
    assert [change.external_id for change in changes] == ["upload-1"]
    document = await connector.fetch_document("upload-1")
    assert document.get_text_content() == "Enterprise policy"
    assert document.external_version == digest
    assert document.acl.to_reader_ids() == [
        "email:owner@example.com",
        "external_group:finance",
    ]
    assert document.acl.is_public is False

    second_changes = await connector.discover_changes(connector.next_checkpoint(), scope)
    assert second_changes == []


@pytest.mark.asyncio
async def test_manual_upload_rejects_paths_outside_base_dir(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "escape.json").write_text(
        json.dumps({"external_id": "escape", "path": str(outside)}),
        encoding="utf-8",
    )
    connector = ManualFileUploadConnector({"base_dir": str(tmp_path)})
    scope = ConnectorScope(
        scope_type="file",
        scope_value="escape",
        display_name="escape",
    )

    with pytest.raises(ValueError, match="escapes base_dir"):
        await connector.discover_changes(SourceCheckpoint(), scope)


def test_local_file_connector_batches_real_documents(tmp_path) -> None:
    paths = []
    for index in range(3):
        path = tmp_path / f"doc-{index}.txt"
        path.write_text(f"content {index}", encoding="utf-8")
        paths.append(path)

    batches = list(LocalFileConnector(paths, batch_size=2).load_from_state())

    assert [len(batch) for batch in batches] == [2, 1]
    assert [item.get_text_content() for batch in batches for item in batch] == [
        "content 0",
        "content 1",
        "content 2",
    ]
    assert all(not item.external_access.is_public for batch in batches for item in batch)
