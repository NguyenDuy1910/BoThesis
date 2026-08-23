from __future__ import annotations

from collections.abc import AsyncIterator
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docling.datamodel.base_models import ConversionStatus, DocumentStream
from docling_core.transforms.chunker import DocChunk, DocMeta
from docling_core.transforms.chunker.line_chunker import LineBasedTokenChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc import (
    BoundingBox as DoclingBoundingBox,
    DescriptionAnnotation,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
    TableCell,
    TableData,
    TextItem,
)

from bothesis.connector.file.file_connector import (
    FILE_SCOPE_VALUE,
    FileConnector,
    LocalFileConnector,
)
from bothesis.connector.file import UnsupportedFileTypeError
from bothesis.connector.file.processing import FileProcessor
from bothesis.connector.processing import DoclingChunker, DoclingProcessor, DocumentMapper
from bothesis.connector.protocol import (
    ConnectorScope,
    DocumentItem,
    DocumentKind,
    ImagePart,
    SourceCheckpoint,
    SourceIdentity,
    SourceProvider,
    StorageObject,
    TablePart,
    TextPart,
)
from bothesis.api import admin as admin_module
from bothesis.services import (
    AdminValidationError,
    AuthContext,
    DatasourceService,
    SOURCE_MANAGE_PERMISSION,
)
from bothesis.services import datasources as datasources_module


class _Converter:
    def __init__(self, document: DoclingDocument) -> None:
        self.document = document
        self.calls: list[tuple[object, dict[str, object]]] = []

    def convert(self, source: object, **kwargs: object) -> object:
        self.calls.append((source, kwargs))
        return SimpleNamespace(
            status=ConversionStatus.SUCCESS,
            errors=[],
            document=self.document,
        )


class _Chunker:
    def __init__(self, chunks: list[DocChunk]) -> None:
        self.chunks = chunks

    def chunk(self, document: DoclingDocument):
        del document
        yield from self.chunks


class _DocumentChunker:
    """Deterministic Docling chunker used at the FileProcessor boundary."""

    def chunk(self, document: DoclingDocument):
        items = [
            item
            for item, _ in document.iterate_items(traverse_pictures=False)
            if getattr(item, "text", "").strip()
        ]
        text = "\n\n".join(str(item.text) for item in items)
        yield DocChunk(text=text, meta=DocMeta(doc_items=items))


class _WhitespaceTokenizer(BaseTokenizer):
    max_tokens: int = 8

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self):
        return self.count_tokens


def _file_processor() -> FileProcessor:
    chunker = _DocumentChunker()
    return FileProcessor(
        chunker=DoclingChunker(
            hybrid_chunker=chunker,
            line_chunker=chunker,
        )
    )


def test_file_processor_extracts_text_and_json_through_docling() -> None:
    processor = _file_processor()

    text = processor.process_bytes(b"alpha\r\n\r\nbeta", file_name="notes.txt")
    assert text.text == "alpha\n\nbeta"
    assert text.sha256 == hashlib.sha256(b"alpha\r\n\r\nbeta").hexdigest()

    structured = processor.process_bytes(b'{"name":"BoThesis"}', file_name="data.json")
    assert '"name": "BoThesis"' in structured.text

    assert structured.item == structured.item.model_validate(
        structured.item.model_dump(mode="json")
    )
    assert structured.chunks[0].item_id == structured.item.id


def test_file_processor_rejects_unsupported_formats() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        _file_processor().process_bytes(b"legacy", file_name="legacy.doc")


def test_file_processor_keeps_a_non_text_image_as_a_document_item() -> None:
    converted = DoclingDocument(name="diagram.png")
    converted.add_picture()
    processor = FileProcessor(
        docling=DoclingProcessor(converter=_Converter(converted)),
        chunker=DoclingChunker(hybrid_chunker=_DocumentChunker()),
    )

    result = processor.process_bytes(b"image-bytes", file_name="diagram.png")

    assert result.item.document_kind == DocumentKind.IMAGE
    assert any(isinstance(part, ImagePart) for part in result.item.content)
    assert result.text == ""
    assert result.chunks == ()


def test_docling_processor_reuses_converter_and_enforces_limits() -> None:
    converted = DoclingDocument(name="policy.pdf")
    converted.add_text(label=DocItemLabel.TEXT, text="Policy")
    converter = _Converter(converted)
    processor = DoclingProcessor(
        converter=converter,
        max_file_bytes=32,
        max_num_pages=8,
        page_range=(2, 5),
    )

    assert processor.process_bytes(b"%PDF", file_name="policy.pdf") is converted
    source, arguments = converter.calls[0]
    assert isinstance(source, DocumentStream)
    assert arguments == {
        "raises_on_error": False,
        "max_num_pages": 8,
        "max_file_size": 32,
        "page_range": (2, 5),
    }
    normalized = processor.process_text(b'{"b": 2, "a": 1}', file_name="data.json")
    assert '"a": 1' in normalized.export_to_markdown()
    assert len(converter.calls) == 1

    with pytest.raises(ValueError, match="32 byte limit"):
        processor.process_bytes(b"x" * 33, file_name="large.pdf")


def test_document_mapper_preserves_structure_storage_and_normalized_provenance() -> None:
    document = DoclingDocument(name="report.pdf")
    document.add_page(page_no=1, size=Size(width=200, height=400))
    document.add_heading(
        "Risk",
        level=1,
        prov=ProvenanceItem(
            page_no=1,
            bbox=DoclingBoundingBox(l=20, t=20, r=180, b=50),
            charspan=(0, 4),
        ),
    )
    document.add_text(
        label=DocItemLabel.PARAGRAPH,
        text="Past due accounts",
        prov=ProvenanceItem(
            page_no=1,
            bbox=DoclingBoundingBox(l=20, t=60, r=180, b=100),
            charspan=(0, 17),
        ),
    )
    cells = [
        TableCell(
            start_row_offset_idx=0,
            end_row_offset_idx=1,
            start_col_offset_idx=0,
            end_col_offset_idx=1,
            text="Account",
            column_header=True,
        ),
        TableCell(
            start_row_offset_idx=1,
            end_row_offset_idx=2,
            start_col_offset_idx=0,
            end_col_offset_idx=1,
            text="A-100",
        ),
    ]
    document.add_table(
        data=TableData(table_cells=cells, num_rows=2, num_cols=1),
        prov=ProvenanceItem(
            page_no=1,
            bbox=DoclingBoundingBox(l=20, t=110, r=180, b=220),
            charspan=(0, 15),
        ),
    )
    caption = document.add_text(label=DocItemLabel.CAPTION, text="Trend chart")
    document.add_picture(
        caption=caption,
        annotations=[
            DescriptionAnnotation(
                text="Balances increase by month",
                provenance="test",
            )
        ],
        prov=ProvenanceItem(
            page_no=1,
            bbox=DoclingBoundingBox(l=20, t=230, r=180, b=350),
            charspan=(0, 11),
        ),
    )
    original = StorageObject(
        provider="cloudflare_r2",
        bucket="documents",
        region="auto",
        key="tenant/report.pdf",
        file_name="report.pdf",
    )

    item = DocumentMapper().to_item(
        document,
        item_id="report",
        title="Report",
        source=_file_source("report"),
        document_kind=DocumentKind.PDF,
        original=original,
    )

    table = next(part for part in item.content if isinstance(part, TablePart))
    assert table.columns == ["Account"]
    assert table.rows == [["A-100"]]
    assert table.section_path == ("Risk",)
    assert table.element_id == "p001_table_001"
    assert table.bounding_box is not None
    assert table.bounding_box.x == pytest.approx(0.1)
    assert table.bounding_box.y == pytest.approx(0.275)
    assert item.original == original
    assert "A-100" in item.get_text_content()
    assert "Balances increase by month" in item.get_text_content()


def test_docling_chunker_maps_multi_page_spans_and_preserves_chunk_text() -> None:
    document = DoclingDocument(name="cross-page.pdf")
    document.add_page(page_no=1, size=Size(width=100, height=100))
    document.add_page(page_no=2, size=Size(width=100, height=100))
    text_item = document.add_text(
        label=DocItemLabel.PARAGRAPH,
        text="alpha\nbeta",
        prov=ProvenanceItem(
            page_no=1,
            bbox=DoclingBoundingBox(l=0, t=0, r=100, b=40),
            charspan=(0, 5),
        ),
    )
    text_item.prov.append(
        ProvenanceItem(
            page_no=2,
            bbox=DoclingBoundingBox(l=0, t=0, r=100, b=40),
            charspan=(6, 10),
        )
    )
    chunk_text = "alpha\nbeta"
    chunker = DoclingChunker(
        hybrid_chunker=_Chunker(
            [
                DocChunk(
                    text=chunk_text,
                    meta=DocMeta(doc_items=[text_item], headings=["Risk"]),
                )
            ]
        )
    )

    chunk = chunker.chunk(document, item_id="cross-page")[0]

    assert chunk.chunk_text == chunk_text
    assert chunk.section_path == ["Risk"]
    assert [(span.page, span.start_offset, span.end_offset) for span in chunk.citation.spans] == [
        (1, 0, 5),
        (2, 6, 10),
    ]
    assert {span.element_id for span in chunk.citation.spans} == {"p001_para_001"}


def test_docling_chunker_preserves_source_native_part_provenance() -> None:
    item = DocumentItem(
        id="page-1",
        title="Policy",
        source=_file_source("page-1"),
        document_kind=DocumentKind.PAGE,
        content=[
            TextPart(
                text="Employees receive 20 days.",
                element_id="paragraph-7",
                page=3,
                section_path=("Benefits",),
            )
        ],
    )

    class NativeChunker:
        def chunk(self, document: DoclingDocument):
            doc_item = next(
                value
                for value, _ in document.iterate_items()
                if isinstance(value, TextItem) and value.text.startswith("Employees")
            )
            yield DocChunk(
                text=doc_item.text,
                meta=DocMeta(doc_items=[doc_item], headings=["Benefits"]),
            )

    chunk = DoclingChunker(hybrid_chunker=NativeChunker()).chunk_item(item)[0]

    assert chunk.citation.spans[0].element_id == "paragraph-7"
    assert chunk.citation.spans[0].page == 3
    assert chunk.citation.spans[0].start_offset == 0
    assert chunk.citation.spans[0].end_offset == len(chunk.chunk_text)
    configured = DoclingChunker(tokenizer=_WhitespaceTokenizer())
    assert configured._resolve_chunker("hybrid").repeat_table_header is True
    assert isinstance(configured._resolve_chunker("line"), LineBasedTokenChunker)


def test_docling_chunker_does_not_infer_offsets_from_repeated_text() -> None:
    document = DoclingDocument(name="repeated.txt")
    repeated = document.add_text(
        label=DocItemLabel.TEXT,
        text="repeat repeat",
    )
    chunker = DoclingChunker(
        hybrid_chunker=_Chunker(
            [DocChunk(text="repeat", meta=DocMeta(doc_items=[repeated]))]
        )
    )

    span = chunker.chunk(document, item_id="repeated")[0].citation.spans[0]

    assert span.element_id == "doc_para_001"
    assert span.start_offset is None
    assert span.end_offset is None


def test_line_chunking_retains_exact_record_element_provenance() -> None:
    document = DoclingProcessor(converter=_Converter(DoclingDocument(name="unused"))).process_text(
        b"first record\nsecond record",
        file_name="events.log",
    )

    chunks = DoclingChunker(tokenizer=_WhitespaceTokenizer()).chunk(
        document,
        item_id="events",
        strategy="line",
    )

    assert [chunk.chunk_text for chunk in chunks] == ["first record", "second record"]
    assert [chunk.citation.spans[0].element_id for chunk in chunks] == [
        "doc_para_001",
        "doc_para_002",
    ]
    assert [
        (chunk.citation.spans[0].start_offset, chunk.citation.spans[0].end_offset)
        for chunk in chunks
    ] == [(0, 12), (0, 13)]


def _file_source(external_id: str) -> SourceIdentity:
    return SourceIdentity(
        connector_id="files",
        provider=SourceProvider.FILE,
        external_id=external_id,
    )


@pytest.mark.asyncio
async def test_file_connector_discovers_incrementally_and_preserves_acl(tmp_path) -> None:
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
    connector = FileConnector(
        {"base_dir": str(tmp_path)},
        processor=_file_processor(),
    )
    scope = ConnectorScope(
        scope_type="source_provider",
        scope_value=FILE_SCOPE_VALUE,
        display_name="Files",
    )

    changes = await connector.discover_changes(SourceCheckpoint(), scope)
    assert [change.item_id for change in changes] == ["upload-1"]
    item = await connector.fetch_item("upload-1")
    assert item.get_text_content() == "Enterprise policy"
    assert item.source.external_version == digest
    assert item.access.to_reader_ids() == [
        "email:owner@example.com",
        "external_group:finance",
    ]
    assert item.access.is_public is False

    second_changes = await connector.discover_changes(connector.next_checkpoint(), scope)
    assert second_changes == []


@pytest.mark.asyncio
async def test_file_connector_rejects_paths_outside_base_dir(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "escape.json").write_text(
        json.dumps({"external_id": "escape", "path": str(outside)}),
        encoding="utf-8",
    )
    connector = FileConnector(
        {"base_dir": str(tmp_path)},
        processor=_file_processor(),
    )
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

    batches = list(
        LocalFileConnector(
            paths,
            batch_size=2,
            processor=_file_processor(),
        ).load_from_state()
    )

    assert [len(batch) for batch in batches] == [2, 1]
    assert [item.get_text_content() for batch in batches for item in batch] == [
        "content 0",
        "content 1",
        "content 2",
    ]
    assert all(not item.access.is_public for batch in batches for item in batch)


def _source_manager() -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        email="manager@example.com",
        display_name="Manager",
        tenant_id=uuid4(),
        role_id=None,
        role_code="source_manager",
        permission_codes=(SOURCE_MANAGE_PERMISSION,),
        principal_tokens=(),
    )


class _AuditRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def record(self, *args, **kwargs) -> None:
        del args
        self.events.append(kwargs)


@pytest.mark.asyncio
async def test_managed_upload_streams_through_a_validated_temporary_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Processor:
        def __init__(self, *, max_file_bytes: int) -> None:
            observed["max_file_bytes"] = max_file_bytes

        def process_path(self, path: Path, *, file_name: str):
            data = path.read_bytes()
            observed.update(
                path=path,
                file_name=file_name,
                content=data,
            )
            return SimpleNamespace(
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                mime_type="text/plain",
            )

    monkeypatch.setattr(datasources_module, "FileProcessor", Processor)
    audit = _AuditRecorder()
    service = DatasourceService(object(), audit=audit)  # type: ignore[arg-type]
    connector = SimpleNamespace(
        id=7,
        provider=SourceProvider.FILE.value,
        settings={"base_dir": str(tmp_path), "max_file_bytes": 32},
    )

    async def resolve_connector(*_):
        return connector

    async def content() -> AsyncIterator[bytes]:
        yield b"Enterprise "
        yield b"policy"

    monkeypatch.setattr(service, "_connector", resolve_connector)
    uploaded = await service.upload_file(
        _source_manager(),
        connector.id,
        file_name="policy.txt",
        content=content(),
    )

    stored_path = tmp_path / f"{uploaded['id']}-policy.txt"
    temporary_path = observed["path"]
    assert isinstance(temporary_path, Path)
    assert observed == {
        "max_file_bytes": 32,
        "path": temporary_path,
        "file_name": "policy.txt",
        "content": b"Enterprise policy",
    }
    assert temporary_path.suffix == ".txt"
    assert not temporary_path.exists()
    assert stored_path.read_bytes() == b"Enterprise policy"
    assert json.loads((tmp_path / f"{uploaded['id']}.json").read_text())["path"] == stored_path.name
    assert audit.events[0]["action"] == "datasource.file_uploaded"


@pytest.mark.asyncio
async def test_managed_upload_stops_at_limit_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedProcessor:
        def __init__(self, **kwargs) -> None:
            del kwargs
            raise AssertionError("oversized upload must not reach file processing")

    monkeypatch.setattr(datasources_module, "FileProcessor", UnexpectedProcessor)
    service = DatasourceService(  # type: ignore[arg-type]
        object(),
        audit=_AuditRecorder(),
    )
    connector = SimpleNamespace(
        id=7,
        provider=SourceProvider.FILE.value,
        settings={"base_dir": str(tmp_path), "max_file_bytes": 5},
    )

    async def resolve_connector(*_):
        return connector

    async def content() -> AsyncIterator[bytes]:
        yield b"1234"
        yield b"56"
        raise AssertionError("upload stream should stop after the oversized chunk")

    monkeypatch.setattr(service, "_connector", resolve_connector)
    with pytest.raises(
        AdminValidationError,
        match=r"File exceeds 5 byte limit: 6 bytes",
    ):
        await service.upload_file(
            _source_manager(),
            connector.id,
            file_name="policy.txt",
            content=content(),
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_admin_managed_upload_uses_request_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    class Service:
        async def upload_file(self, actor, connector_id, *, file_name, content):
            received.update(
                actor=actor,
                connector_id=connector_id,
                file_name=file_name,
                content=b"".join([chunk async for chunk in content]),
            )
            return {"id": "upload-1"}

    class StreamingRequest:
        def stream(self):
            async def chunks() -> AsyncIterator[bytes]:
                yield b"alpha"
                yield b"beta"

            return chunks()

        async def body(self) -> bytes:
            raise AssertionError("request.body() must not buffer managed uploads")

    monkeypatch.setattr(admin_module, "_datasources", lambda _: Service())
    actor = _source_manager()
    result = await admin_module.upload_datasource_file(
        7,
        StreamingRequest(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        actor,
        "policy%20file.txt",
    )

    assert result == {"id": "upload-1"}
    assert received == {
        "actor": actor,
        "connector_id": 7,
        "file_name": "policy file.txt",
        "content": b"alphabeta",
    }
