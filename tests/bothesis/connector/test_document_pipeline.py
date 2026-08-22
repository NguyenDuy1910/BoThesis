from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast
from uuid import uuid4
from zipfile import ZipFile

import pytest

from bothesis.connector.file.processing import (
    FileProcessor,
    FileProcessingError,
    ParsedDocument,
    ParsedSection,
)
from bothesis.document_index.raw_storage import aws_s3
from bothesis.db.models import Document, DocumentChunk
from bothesis.services import AuthContext, UploadService, UploadTooLargeError
from bothesis.connector.document_pipeline import (
    DocumentChunker,
    DocumentPipeline,
    OCRUnavailableError,
    PARSER_VERSION,
    CHUNKER_VERSION,
)
from bothesis.connector.provider_cache import ProviderCacheEntry
from bothesis.document_index.raw_storage import (
    ObjectStorageError,
    PresignedRequest,
    S3DocumentStorage,
)
from bothesis.document_index.vector_store import QdrantDocumentIndex


class _Embedder:
    model = "test-embedding-v1"

    async def embed_query(self, query: str) -> list[float]:
        return [float(len(query))]

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        return [[float(len(document))] for document in documents]


class _NoopVectorIndex:
    async def replace_document(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def search_document(self, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
        return ()

    async def update_document_access(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def soft_delete_document(self, document_id: Any) -> None:
        return None


class _NoopProviderCache:
    async def get(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def put(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def invalidate(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def clear(self, *args: Any, **kwargs: Any) -> None:
        return None


class _CachedProviderFile(_NoopProviderCache):
    def __init__(self, entry: ProviderCacheEntry | None = None) -> None:
        self.entry = entry

    async def get(self, *args: Any, **kwargs: Any) -> ProviderCacheEntry | None:
        return self.entry


class _SignedStorage:
    def __init__(self) -> None:
        self.downloads = 0

    def presign_download(self, key: str, *, expires_seconds: int) -> PresignedRequest:
        self.downloads += 1
        return PresignedRequest(
            url=f"https://objects.example.test/{key}?expires={expires_seconds}",
            method="GET",
            headers={},
            expires_at=datetime.now(UTC),
        )


class _EmptyParser:
    def parse(self, raw_bytes: bytes, *, file_name: str) -> ParsedDocument:
        raise FileProcessingError(f"no text in {file_name}")


def _processor(*, direct_max_bytes: int = 20 * 1024 * 1024) -> DocumentPipeline:
    return DocumentPipeline(
        cast(Any, None),
        object_storage=None,
        parser=_EmptyParser(),
        chunker=DocumentChunker(),
        embedder=_Embedder(),
        vector_index=_NoopVectorIndex(),
        provider_cache=_NoopProviderCache(),
        direct_max_bytes=direct_max_bytes,
    )


def _access(user_id: Any, tenant_id: Any | None = None) -> AuthContext:
    return AuthContext(
        user_id=user_id,
        email="person@example.test",
        display_name="Person",
        tenant_id=tenant_id,
        role_id=uuid4() if tenant_id else None,
        role_code="analyst" if tenant_id else None,
        permission_codes=("knowledge.read",) if tenant_id else (),
        principal_tokens=(),
    )


def _document(
    content_type: str,
    *,
    size_bytes: int = 1024,
    indexing_status: str = "none",
    processing: dict[str, str] | None = None,
) -> Document:
    document = Document(
        id=uuid4(),
        owner_user_id=uuid4(),
        tenant_id=None,
        origin="upload",
        title="sample",
        mime_type=content_type,
        size_bytes=size_bytes,
        upload_status="available",
        indexing_status=indexing_status,
        lifecycle_status="active",
        metadata_={"file_name": "sample", "processing": processing}
        if processing
        else {"file_name": "sample"},
    )
    document.content_sha256 = "a" * 64
    return document


def test_routing_precedence_prefers_images_then_current_index_then_small_pdf() -> None:
    processor = _processor()
    tenant_id = uuid4()

    def route(document: Document, *, current: bool = False) -> str:
        if current:
            document.indexing_status = "indexed"
            document.metadata_["processing"] = {
                "source_fingerprint": "a" * 64,
                "parser_version": PARSER_VERSION,
                "chunker_version": CHUNKER_VERSION,
                "embedding_model": _Embedder.model,
                "tenant_id": str(tenant_id),
                "owner_user_id": str(document.owner_user_id),
            }
        return processor._route(document)

    assert route(_document("image/png"), current=True) == "direct"
    assert route(_document("application/pdf"), current=True) == "indexed"
    assert route(_document("application/pdf")) == "direct"
    assert route(_document("application/pdf", size_bytes=21 * 1024 * 1024)) == "indexed"
    assert (
        route(
            _document(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        )
        == "indexed"
    )


def test_chunker_preserves_page_heading_and_sheet_lineage() -> None:
    parsed = ParsedDocument(
        file_name="report.xlsx",
        sections=(
            ParsedSection(
                content="Revenue\n100\n200",
                page_number=4,
                heading_path=("Financials", "Revenue"),
                metadata={"sheet_name": "Financials", "sheet_index": 2},
            ),
        ),
        raw_bytes=b"xlsx",
        size_bytes=4,
        sha256="b" * 64,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    chunks = DocumentChunker(max_characters=100, overlap_characters=10).chunk(parsed)

    assert len(chunks) == 1
    assert chunks[0].start_page_number == 4
    assert chunks[0].end_page_number == 4
    assert chunks[0].heading_path == ("Financials", "Revenue")
    assert chunks[0].metadata == {"sheet_name": "Financials", "sheet_index": 2}


def test_chunker_keeps_multi_page_provenance_inside_one_semantic_chunk() -> None:
    parsed = ParsedDocument(
        file_name="report.pdf",
        sections=(
            ParsedSection(content="Page one evidence", element_id="p001_para01", page_number=1),
            ParsedSection(content="Page two evidence", element_id="p002_para01", page_number=2),
        ),
        raw_bytes=b"pdf",
        size_bytes=3,
        sha256="c" * 64,
        mime_type="application/pdf",
    )

    chunks = DocumentChunker(max_characters=100, overlap_characters=0).chunk(parsed)

    assert len(chunks) == 1
    assert [(span.page, span.element_id) for span in chunks[0].citation_spans] == [
        (1, "p001_para01"),
        (2, "p002_para01"),
    ]
    assert chunks[0].start_page_number == 1
    assert chunks[0].end_page_number == 2


def test_office_parsers_emit_docx_xlsx_and_pptx_sections() -> None:
    processor = FileProcessor()

    docx = BytesIO()
    with ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:w"><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Risk</w:t></w:r></w:p>'
            "<w:p><w:r><w:t>Mitigation details</w:t></w:r></w:p>"
            "</w:body></w:document>",
        )
    docx_sections = processor.parse_bytes(
        docx.getvalue(), file_name="brief.docx"
    ).sections
    assert docx_sections[0].heading_path == ("Risk",)
    assert "Mitigation details" in docx_sections[0].content

    xlsx = BytesIO()
    with ZipFile(xlsx, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="urn:x"><sheets><sheet name="Revenue"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="urn:x"><si><t>Quarter</t></si><si><t>Q1</t></si></sst>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="urn:x"><sheetData><row>'
            '<c t="s"><v>0</v></c><c t="s"><v>1</v></c>'
            "</row></sheetData></worksheet>",
        )
    xlsx_sections = processor.parse_bytes(
        xlsx.getvalue(), file_name="data.xlsx"
    ).sections
    assert xlsx_sections[0].heading_path == ("Revenue",)
    assert xlsx_sections[0].metadata["sheet_name"] == "Revenue"
    assert xlsx_sections[0].content == "Quarter Q1"

    pptx = BytesIO()
    with ZipFile(pptx, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:t>Strategy</a:t></p:sld>',
        )
    pptx_sections = processor.parse_bytes(
        pptx.getvalue(), file_name="deck.pptx"
    ).sections
    assert pptx_sections[0].heading_path == ("Slide 1",)
    assert pptx_sections[0].metadata["slide_number"] == 1


@pytest.mark.asyncio
async def test_image_retrieval_without_ocr_has_a_clear_failure() -> None:
    with pytest.raises(OCRUnavailableError, match="no OCR parser is configured"):
        await _processor()._parse(
            b"image",
            file_name="scan.png",
            content_type="image/png",
        )


@pytest.mark.asyncio
async def test_direct_inputs_use_signed_urls_and_replay_cached_pdf_annotations() -> (
    None
):
    storage = _SignedStorage()
    cache = _CachedProviderFile()
    processor = DocumentPipeline(
        cast(Any, None),
        object_storage=cast(Any, storage),
        parser=_EmptyParser(),
        chunker=DocumentChunker(),
        embedder=_Embedder(),
        vector_index=_NoopVectorIndex(),
        provider_cache=cache,
    )
    image = _document("image/png")
    image.raw_storage_key = "users/u/documents/image/raw"

    context, _ = await processor._prepare_direct(image)

    assert context.content_block == {
        "type": "image_url",
        "image_url": {
            "url": "https://objects.example.test/users/u/documents/image/raw?expires=300"
        },
    }
    assert storage.downloads == 1

    annotation = {
        "type": "file",
        "file": {
            "hash": "provider-hash",
            "content": [{"type": "text", "text": "cached"}],
        },
    }
    cache.entry = ProviderCacheEntry(
        provider="openrouter",
        source_fingerprint="a" * 64,
        reference={"annotations": [annotation]},
    )
    pdf = _document("application/pdf")
    pdf.raw_storage_key = "users/u/documents/pdf/raw"

    context, _ = await processor._prepare_direct(pdf)

    assert context.content_block is None
    assert context.provider_annotations == (annotation,)
    assert storage.downloads == 1


def test_upload_limits_keep_large_content_out_of_database_fallback() -> None:
    uploads = UploadService(
        cast(Any, None),
        object_storage=None,
        max_upload_bytes=100,
        max_database_blob_bytes=20,
    )

    uploads._validate_upload_size(100)
    uploads._validate_database_size(20)
    with pytest.raises(UploadTooLargeError):
        uploads._validate_upload_size(101)
    with pytest.raises(UploadTooLargeError):
        uploads._validate_database_size(21)


class _PresigningS3Client:
    def __init__(self) -> None:
        self.operation = ""
        self.parameters: dict[str, str] = {}
        self.expires_in = 0
        self.method = ""

    def generate_presigned_url(
        self,
        operation: str,
        *,
        Params: dict[str, str],
        ExpiresIn: int,
        HttpMethod: str,
    ) -> str:
        self.operation = operation
        self.parameters = Params
        self.expires_in = ExpiresIn
        self.method = HttpMethod
        return (
            "https://documents.s3.amazonaws.com/users/user-1/documents/id/raw?signed=1"
        )


def test_s3_presigned_put_is_scoped_and_bounded() -> None:
    client = _PresigningS3Client()
    storage = S3DocumentStorage(bucket="documents", client=client)

    request = storage.presign_upload(
        "users/user 1/documents/id/raw",
        content_type="application/pdf",
        expires_seconds=600,
    )
    assert request.method == "PUT"
    assert request.headers == {"Content-Type": "application/pdf"}
    assert request.url.endswith("?signed=1")
    assert client.operation == "put_object"
    assert client.parameters == {
        "Bucket": "documents",
        "Key": "users/user 1/documents/id/raw",
        "ContentType": "application/pdf",
    }
    assert client.expires_in == 600
    assert client.method == "PUT"


def test_s3_constructor_uses_the_standard_boto_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _PresigningS3Client()
    captured: dict[str, Any] = {}

    class _Session:
        def __init__(self, *, region_name: str | None) -> None:
            captured["region_name"] = region_name

        def client(self, service: str, **kwargs: Any) -> _PresigningS3Client:
            captured["service"] = service
            captured["client_kwargs"] = kwargs
            return client

    monkeypatch.setattr(aws_s3.boto3, "Session", _Session)

    storage = S3DocumentStorage(
        bucket="documents",
        region="ap-southeast-1",
    )

    assert isinstance(storage, S3DocumentStorage)
    assert captured["region_name"] == "ap-southeast-1"
    assert captured["service"] == "s3"
    assert captured["client_kwargs"]["endpoint_url"] is None
    assert "aws_access_key_id" not in captured["client_kwargs"]
    assert "aws_secret_access_key" not in captured["client_kwargs"]


def test_cloudflare_r2_uses_the_same_boto3_s3_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _PresigningS3Client()
    captured: dict[str, Any] = {}

    class _Session:
        def __init__(self, **kwargs: str | None) -> None:
            captured["session_kwargs"] = kwargs

        def client(self, service: str, **kwargs: Any) -> _PresigningS3Client:
            captured["service"] = service
            captured["client_kwargs"] = kwargs
            return client

    monkeypatch.setattr(aws_s3.boto3, "Session", _Session)

    storage = S3DocumentStorage.for_cloudflare_r2(
        bucket="documents",
        account_id="account-id",
        access_key_id="r2-access-key",
        secret_access_key="r2-secret-key",
    )

    assert storage.provider == "cloudflare_r2"
    assert storage.bucket == "documents"
    assert captured["session_kwargs"] == {
        "region_name": "auto",
        "aws_access_key_id": "r2-access-key",
        "aws_secret_access_key": "r2-secret-key",
    }
    assert captured["service"] == "s3"
    assert captured["client_kwargs"]["endpoint_url"] == (
        "https://account-id.r2.cloudflarestorage.com"
    )
    assert captured["client_kwargs"]["config"].s3 == {"addressing_style": "path"}


class _S3Body:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self.closed = False

    def read(self, limit: int) -> bytes:
        return self._content[:limit]

    def close(self) -> None:
        self.closed = True


class _ReadingS3Client:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.body = _S3Body(content)
        self.get_calls = 0

    def head_object(self, **kwargs: str) -> dict[str, Any]:
        return {"ContentLength": len(self.content)}

    def get_object(self, **kwargs: str) -> dict[str, Any]:
        self.get_calls += 1
        return {"Body": self.body}


@pytest.mark.asyncio
async def test_s3_read_is_bounded_before_downloading_content() -> None:
    client = _ReadingS3Client(b"four")
    storage = S3DocumentStorage(bucket="documents", client=client)

    with pytest.raises(ObjectStorageError, match="read limit"):
        await storage.read("documents/id/raw", max_bytes=3)

    assert client.get_calls == 0


@pytest.mark.asyncio
async def test_s3_read_closes_the_stream() -> None:
    client = _ReadingS3Client(b"content")
    storage = S3DocumentStorage(bucket="documents", client=client)

    content = await storage.read("documents/id/raw", max_bytes=7)

    assert content == b"content"
    assert client.get_calls == 1
    assert client.body.closed is True


class _RecordingVectorStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.batches: list[list[Any]] = []
        self.access_updates: list[tuple[str, dict[str, Any]]] = []

    async def soft_delete_document_points(self, document_id: str) -> None:
        self.deleted.append(document_id)

    async def upsert_points(self, points: list[Any]) -> None:
        self.batches.append(points)

    async def set_document_payload(
        self,
        document_id: str,
        payload: dict[str, Any],
    ) -> None:
        self.access_updates.append((document_id, payload))


@pytest.mark.asyncio
async def test_vector_replacement_uses_deterministic_points_and_reader_acl() -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    document = _document("text/plain")
    document.owner_user_id = user_id
    chunks = [
        DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            chunk_index=0,
            content="grounded content",
            metadata_={"sheet_name": "Summary"},
        )
    ]
    access = AuthContext(
        user_id=user_id,
        email="person@example.test",
        display_name="Person",
        tenant_id=tenant_id,
        role_id=uuid4(),
        role_code="analyst",
        permission_codes=("knowledge.read",),
        principal_tokens=(),
    )
    store = _RecordingVectorStore()
    index = QdrantDocumentIndex(cast(Any, store))

    await index.replace_document(
        document,
        chunks,
        [[0.1, 0.2]],
        access=access,
        embedding_model="embedding-v1",
        source_fingerprint="a" * 64,
    )
    await index.replace_document(
        document,
        chunks,
        [[0.3, 0.4]],
        access=access,
        embedding_model="embedding-v1",
        source_fingerprint="a" * 64,
    )

    assert store.deleted == [str(document.id), str(document.id)]
    assert store.batches[0][0].id == store.batches[1][0].id
    payload = store.batches[0][0].payload
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["reader_ids"] == [str(user_id)]
    assert payload["item_id"] == str(document.id)
    assert payload["chunk_id"] == f"{document.id}:0"
    assert payload["chunk_text"] == "grounded content"
    assert "Document: sample" in payload["contextual_text"]
    assert payload["content_type"] == "text"
    assert "access" not in payload
    assert "storage" not in payload

    await index.update_document_access(document.id, access=access)
    assert store.access_updates == [
        (
            str(document.id),
            {
                "tenant_id": str(tenant_id),
                "reader_ids": [str(user_id)],
            },
        )
    ]

    await index.soft_delete_document(document.id)
    assert store.deleted == [str(document.id), str(document.id), str(document.id)]


def test_provider_cache_expiry_uses_utc() -> None:
    from bothesis.connector.provider_cache import ProviderCacheEntry

    entry = ProviderCacheEntry(
        provider="openrouter",
        source_fingerprint="a" * 64,
        reference={"file_id": "file-123"},
        expires_at=datetime(2000, 1, 1, tzinfo=UTC),
    )

    assert entry.is_expired
