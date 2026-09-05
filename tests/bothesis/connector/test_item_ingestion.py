from __future__ import annotations

import ast
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import bothesis.services.item_ingestion as item_ingestion
import pytest
from bothesis.connector.protocol import (
    AccessPolicy,
    Chunk,
    CitationInfo,
    CitationSpan,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    ProviderCacheEntry,
    SourceIdentity,
    SourceProvider,
)
from bothesis.db.models import Item, ItemUpload
from bothesis.document_index import IndexingContext, ItemIndex
from bothesis.storage import (
    ObjectStorageError,
    PresignedRequest,
    S3DocumentStorage,
    StoredObject,
    aws_s3,
)
from bothesis.services import (
    AuthContext,
    DocumentProcessingError,
    UploadTooLargeError,
)
from bothesis.services.item_ingestion import ItemIngestionService
from bothesis.services.document_upload import DocumentUploadService
from bothesis.services.stored_file_content import StoredFileContentService
from bothesis.services.preview import KnowledgePreview
from PIL import Image


class _Embedder:
    embedding_model = "test-embedding-v1"

    async def embed_query(self, query: str) -> list[float]:
        return [float(len(query))]

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        return [[float(len(document))] for document in documents]


@pytest.mark.asyncio
async def test_item_ingestion_owns_the_source_neutral_indexing_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class SessionFactory:
        def begin(self) -> SessionFactory:
            return self

        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: Any) -> None:
            return None

    class Items:
        def __init__(self, _: object) -> None:
            pass

        async def mark_processing(self, _: Any) -> None:
            events.append("processing")

        async def merge_metadata(self, _: Any, values: dict[str, Any]) -> None:
            assert values["processing"]["source"] == "test"
            events.append("metadata")

        async def mark_ready(self, _: Any) -> None:
            events.append("ready")

        async def mark_failed(self, _: Any) -> None:
            events.append("failed")

    class Citations:
        def __init__(self, _: object) -> None:
            pass

        async def replace_for_item(self, _: Any, chunks: Any) -> None:
            assert len(chunks) == 1
            events.append("citations")

    class Index:
        async def index_item_content(
            self,
            _: DocumentItem,
            chunks: Any,
            *,
            context: IndexingContext,
        ) -> int:
            assert len(chunks) == 1
            assert context.connector_key == "file"
            events.append("vectors")
            return len(chunks)

    monkeypatch.setattr(item_ingestion, "ItemService", Items)
    monkeypatch.setattr(item_ingestion, "CitationService", Citations)
    stored = _document("text/plain")
    canonical = DocumentItem(
        id=str(stored.id),
        title=stored.title or "sample",
        document_kind=DocumentKind.NOTE,
        source=SourceIdentity(
            connector_id="upload",
            provider=SourceProvider.FILE,
            external_id=str(stored.id),
        ),
        hierarchy=Hierarchy(parent_id=str(stored.parent_item_id)),
        access=AccessPolicy(),
    )
    chunk = Chunk(
        id=f"{stored.id}:0",
        item_id=str(stored.id),
        chunk_index=0,
        chunk_text="grounded content",
        content_type="text",
        citation=CitationInfo(),
    )
    ingestion = ItemIngestionService(
        cast(Any, SessionFactory()),
        index=cast(Any, Index()),
    )

    count = await ingestion.process_item_content(
        stored,
        canonical,
        [chunk],
        context=IndexingContext(
            tenant_id=str(stored.tenant_id),
            collection_item_id=str(stored.parent_item_id),
            parent_item_id=str(stored.parent_item_id),
            document_type=stored.document_type or "plain_text",
            connector_key="file",
        ),
        processing_metadata={"source": "test"},
    )

    assert count == 1
    assert events == ["processing", "citations", "vectors", "metadata", "ready"]


def _access(user_id: Any, tenant_id: Any | None = None) -> AuthContext:
    return AuthContext(
        user_id=user_id,
        email="person@example.test",
        display_name="Person",
        tenant_id=tenant_id,
        role_id=uuid4() if tenant_id else None,
        role_code="analyst" if tenant_id else None,
        permission_codes=("knowledge.read",) if tenant_id else (),
        group_ids=(),
    )


def _document(
    content_type: str,
    *,
    size_bytes: int = 1024,
    status: str = "ready",
    processing: dict[str, str] | None = None,
) -> Item:
    owner_id = uuid4()
    collection_id = uuid4()
    document = Item(
        id=uuid4(),
        item_type="document",
        document_type="plain_text",
        parent_item_id=collection_id,
        parent_relation="contains",
        tenant_id=uuid4(),
        title="sample",
        mime_type=content_type,
        size_bytes=size_bytes,
        status=status,
        metadata_={"file_name": "sample", "processing": processing}
        if processing
        else {"file_name": "sample"},
    )
    document.upload = ItemUpload(
        item_id=document.id,
        tenant_id=document.tenant_id,
        owner_user_id=owner_id,
        idempotency_key="test",
        status="available",
    )
    return document


def test_upload_limits_reject_oversize_objects() -> None:
    uploads = DocumentUploadService(
        cast(Any, None),
        object_storage=cast(Any, SimpleNamespace()),
        ingestion_service=cast(Any, SimpleNamespace()),
        document_source=cast(Any, SimpleNamespace()),
        max_upload_bytes=100,
    )

    uploads._validate_upload_size(100)
    with pytest.raises(UploadTooLargeError):
        uploads._validate_upload_size(101)


class _StreamingStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.downloads = 0
        self.reads = 0

    async def download_to_path(
        self,
        key: str,
        path: Path,
        *,
        max_bytes: int,
    ) -> StoredObject:
        del key
        assert len(self.content) <= max_bytes
        self.downloads += 1
        path.write_bytes(self.content)
        return StoredObject(
            size_bytes=len(self.content),
            content_type="text/plain",
        )

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        del key, max_bytes
        self.reads += 1
        raise AssertionError("streamed indexing must not read the full object")


class _PathProcessor:
    def __init__(self) -> None:
        self.content: bytes | None = None

    def process_path(self, path: Path, **kwargs: Any) -> object:
        self.content = path.read_bytes()
        item_id = str(kwargs["item_id"])
        source = cast(SourceIdentity, kwargs["source"])
        item = DocumentItem(
            id=item_id,
            title=str(kwargs["title"]),
            document_kind=cast(DocumentKind, kwargs["document_kind"]),
            source=source,
            access=cast(AccessPolicy, kwargs["access"]),
        )
        chunk = Chunk(
            id=f"{item_id}:0",
            item_id=item_id,
            chunk_index=0,
            chunk_text="streamed evidence",
            content_type="text",
            citation=CitationInfo(spans=(CitationSpan(element_id="doc_para_001"),)),
        )
        return SimpleNamespace(
            item=item,
            chunks=(chunk,),
        )


@pytest.mark.asyncio
async def test_index_processing_streams_object_storage_to_a_temporary_path() -> None:
    raw = b"bounded source content"
    storage = _StreamingStorage(raw)
    source_processor = _PathProcessor()
    service = StoredFileContentService(
        object_storage=cast(Any, storage),
        processor=cast(Any, source_processor),
    )
    document = _document("text/plain", size_bytes=len(raw))
    document.storage_key = "tenant/document/raw"

    processed = await service.canonicalize(
        document,
        access=_access(document.upload.owner_user_id, uuid4()),
    )

    assert storage.downloads == 1
    assert storage.reads == 0
    assert source_processor.content == raw
    assert processed.chunks[0].chunk_text == "streamed evidence"
    assert processed.item.id == str(document.id)


@pytest.mark.asyncio
async def test_index_processing_rejects_oversize_source_before_download() -> None:
    storage = _StreamingStorage(b"oversize")
    service = StoredFileContentService(
        object_storage=cast(Any, storage),
        processor=cast(Any, _PathProcessor()),
        max_processing_bytes=4,
    )
    document = _document("text/plain", size_bytes=8)
    document.storage_key = "tenant/document/raw"

    with pytest.raises(DocumentProcessingError, match="processing limit"):
        await service.canonicalize(
            document,
            access=_access(document.upload.owner_user_id, uuid4()),
        )

    assert storage.downloads == 0
    assert storage.reads == 0


def test_item_ingestion_has_no_raw_processing_implementation_dependencies() -> None:
    source_path = Path(cast(str, item_ingestion.__file__))
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert not any(
        module.startswith(
            ("bothesis.connector.file", "bothesis.connector.processing", "bothesis.storage")
        )
        for module in imported_modules
    )
    assert not {"asyncio", "base64", "hashlib", "tempfile"} & imported_modules
    assert "_process_source" not in {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert "EmbeddingService" not in {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }


class _PresigningS3Client:
    def __init__(self) -> None:
        self.operation = ""
        self.parameters: dict[str, Any] = {}
        self.expires_in = 0
        self.method = ""
        self.uploaded_body: bytes | None = None

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

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.operation = "put_object"
        self.parameters = kwargs
        body = kwargs.get("Body")
        if hasattr(body, "read"):
            self.uploaded_body = body.read()
        return {"ETag": '"etag-1"'}


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


def test_s3_put_bytes_uses_the_same_object_storage_boundary() -> None:
    client = _PresigningS3Client()
    storage = S3DocumentStorage(bucket="documents", client=client)

    stored = storage.put_bytes(
        b"raw document",
        "files/document-1/report.txt",
        content_type="text/plain",
    )

    assert client.parameters == {
        "Bucket": "documents",
        "Key": "files/document-1/report.txt",
        "Body": b"raw document",
        "ContentType": "text/plain",
    }
    assert stored.size_bytes == len(b"raw document")
    assert stored.content_type == "text/plain"
    assert stored.etag == "etag-1"


def test_s3_put_path_streams_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "report.txt"
    path.write_bytes(b"raw document")
    client = _PresigningS3Client()
    storage = S3DocumentStorage(bucket="documents", client=client)

    storage.put_path(
        path,
        "files/document-1/report.txt",
        content_type="text/plain",
    )

    assert client.uploaded_body == b"raw document"
    assert client.parameters["Bucket"] == "documents"
    assert client.parameters["Key"] == "files/document-1/report.txt"


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
        self._position = 0
        self.closed = False

    def read(self, limit: int) -> bytes:
        block = self._content[self._position : self._position + limit]
        self._position += len(block)
        return block

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


@pytest.mark.asyncio
async def test_s3_download_to_path_streams_content(tmp_path: Path) -> None:
    client = _ReadingS3Client(b"streamed content")
    storage = S3DocumentStorage(bucket="documents", client=client)
    destination = tmp_path / "downloaded.bin"

    stored = await storage.download_to_path(
        "documents/id/raw",
        destination,
        max_bytes=100,
    )

    assert destination.read_bytes() == b"streamed content"
    assert stored.size_bytes == len(b"streamed content")
    assert client.body.closed is True


class _RecordingIndexBackend:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.deleted_tenants: list[str | None] = []
        self.batches: list[tuple[list[Any], list[list[float]]]] = []

    async def replace_item_points(
        self,
        *,
        item_id: str,
        tenant_id: str,
        records: Any,
        vectors: Any,
    ) -> None:
        self.deleted.append(item_id)
        self.deleted_tenants.append(tenant_id)
        self.batches.append((list(records), [list(vector) for vector in vectors]))

    async def tombstone_item_points(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
    ) -> None:
        self.deleted.append(document_id)
        self.deleted_tenants.append(tenant_id)


@pytest.mark.asyncio
async def test_item_index_replacement_uses_deterministic_bounded_payloads() -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    document = _document("text/plain")
    item = DocumentItem(
        id=str(document.id),
        title="sample",
        document_kind=DocumentKind.NOTE,
        source=SourceIdentity(
            connector_id="file",
            provider=SourceProvider.FILE,
            external_id=str(document.id),
        ),
        hierarchy=Hierarchy(parent_id=str(document.parent_item_id)),
        access=AccessPolicy.from_reader_ids([str(user_id)]),
    )
    chunks = [
        Chunk(
            id=f"{document.id}:0",
            item_id=str(document.id),
            chunk_index=0,
            content_type="text",
            chunk_text="grounded content",
            citation=CitationInfo(
                section="Summary",
                section_path=("Summary",),
                spans=(CitationSpan(element_id="doc_para_001"),),
            ),
        )
    ]
    backend = _RecordingIndexBackend()
    index = ItemIndex(backend=cast(Any, backend), embedder=_Embedder())

    await index.index_item_content(
        item,
        chunks,
        context=IndexingContext(
            tenant_id=str(tenant_id),
            collection_item_id=str(document.parent_item_id),
            parent_item_id=str(document.parent_item_id),
            document_type=document.document_type or "plain_text",
            connector_key="file",
        ),
    )
    await index.index_item_content(
        item,
        chunks,
        context=IndexingContext(
            tenant_id=str(tenant_id),
            collection_item_id=str(document.parent_item_id),
            parent_item_id=str(document.parent_item_id),
            document_type=document.document_type or "plain_text",
            connector_key="file",
        ),
    )

    assert backend.deleted == [str(document.id), str(document.id)]
    assert backend.deleted_tenants == [str(tenant_id), str(tenant_id)]
    assert backend.batches[0][0][0].point_id == backend.batches[1][0][0].point_id
    payload = backend.batches[0][0][0].payload.to_payload()
    expected_text = "Document: sample\n\ngrounded content"
    assert backend.batches[0][1] == [[float(len(expected_text))]]
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["collection_item_id"] == str(document.parent_item_id)
    assert "integration_connection_id" not in payload
    assert "ingestion_source_id" not in payload
    assert "embedding_model" not in payload
    assert "root_id" not in payload
    assert "context_section_path" not in payload
    assert "citation_section_path" not in payload
    assert "citation_section" not in payload
    assert "context_summary" not in payload
    assert "citation_spans" not in payload
    assert payload["item_id"] == str(document.id)
    assert payload["chunk_id"] == f"{document.id}:0"
    assert payload["chunk_text"] == "grounded content"
    assert "Document: sample" in payload["contextual_text"]
    assert payload["content_type"] == "text"
    assert payload["section_path"] == ["Summary"]
    assert "access" not in payload
    assert "storage" not in payload

    await index.remove_item_content(str(document.id), tenant_id=str(tenant_id))
    assert backend.deleted == [str(document.id), str(document.id), str(document.id)]


def test_provider_cache_expiry_uses_utc() -> None:
    entry = ProviderCacheEntry(
        provider="openrouter",
        provider_version="v1",
        reference={"file_id": "file-123"},
        expires_at=datetime(2000, 1, 1, tzinfo=UTC),
    )

    assert entry.is_expired


class _PreviewStorage:
    def __init__(self, source: bytes, *, content_type: str) -> None:
        self.source = source
        self.content_type = content_type
        self.downloads = 0
        self.puts: dict[str, tuple[bytes, str | None]] = {}

    async def head(self, key: str) -> StoredObject:
        assert key == "tenants/t/items/i/raw"
        return StoredObject(
            size_bytes=len(self.source),
            content_type=self.content_type,
            etag="source-etag",
        )

    async def download_to_path(
        self,
        key: str,
        path: Path,
        *,
        max_bytes: int,
    ) -> StoredObject:
        assert key == "tenants/t/items/i/raw"
        assert len(self.source) <= max_bytes
        self.downloads += 1
        path.write_bytes(self.source)
        return await self.head(key)

    def put_bytes(
        self,
        data: bytes,
        key: str,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        self.puts[key] = (data, content_type)
        return StoredObject(size_bytes=len(data), content_type=content_type)

    def presign_download(self, key: str, *, expires_seconds: int) -> PresignedRequest:
        return PresignedRequest(
            url=f"https://objects.example.test/{key}?expires={expires_seconds}",
            method="GET",
            headers={},
            expires_at=datetime.now(UTC),
        )


def _preview_document(content_type: str, source: bytes, *, file_name: str) -> Item:
    document = _document(content_type, size_bytes=len(source))
    document.storage_key = "tenants/t/items/i/raw"
    document.metadata_ = {"file_name": file_name}
    return document


@pytest.mark.asyncio
async def test_knowledge_preview_derives_versioned_webp_without_replacing_original(
    tmp_path: Path,
) -> None:
    source_buffer = BytesIO()
    Image.new("RGB", (2_400, 1_200), "navy").save(source_buffer, "PNG")
    source = source_buffer.getvalue()
    source_path = tmp_path / "source.png"
    source_path.write_bytes(source)
    storage = _PreviewStorage(source, content_type="image/png")
    service = KnowledgePreview(
        cast(Any, storage),
        max_dimension=800,
    )
    document = _preview_document("image/png", source, file_name="photo.png")

    manifest = await service.generate(document, source_path=source_path)

    assert manifest is not None
    assert manifest.representation == "image"
    assert manifest.page_count == 1
    assert len(manifest.assets) == 1
    asset = manifest.assets[0]
    assert asset.page == 1
    assert (asset.width, asset.height) == (800, 400)
    assert asset.content_type == "image/webp"
    assert asset.key.endswith("/page-0001.webp")
    assert storage.source == source
    rendered, rendered_type = storage.puts[asset.key]
    assert rendered_type == "image/webp"
    with Image.open(BytesIO(rendered)) as preview:
        assert preview.format == "WEBP"

    document.metadata_["preview"] = manifest.model_dump(mode="json")
    assert await service.generate(document, source_path=source_path) == manifest
    assert len(storage.puts) == 1

    resolved = service.resolve(document, expires_seconds=300)
    assert resolved is not None
    assert resolved.original.content_type == "image/png"
    assert resolved.assets[0].page == 1
    assert resolved.coordinate_space == "normalized_top_left"


@pytest.mark.asyncio
async def test_office_preview_uses_the_consistent_original_representation() -> None:
    source = b"office source remains authoritative"
    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    storage = _PreviewStorage(source, content_type=content_type)
    service = KnowledgePreview(cast(Any, storage))
    document = _preview_document(content_type, source, file_name="report.docx")

    manifest = await service.generate(document)

    assert manifest is not None
    assert manifest.representation == "original"
    assert manifest.assets == ()
    assert storage.downloads == 0
    assert storage.puts == {}


def test_pdf_preview_pages_are_bounded_and_keep_one_based_page_mapping(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "report.pdf"
    first = Image.new("RGB", (400, 600), "white")
    second = Image.new("RGB", (600, 400), "gray")
    try:
        first.save(pdf_path, "PDF", save_all=True, append_images=[second])
    finally:
        first.close()
        second.close()

    preview = KnowledgePreview(cast(Any, object()), max_pages=1, max_dimension=600).render(
        pdf_path,
        file_name="report.pdf",
        content_type="application/pdf",
    )

    assert preview.representation == "pages"
    assert preview.page_count == 2
    assert preview.truncated is True
    assert [asset.page for asset in preview.assets] == [1]
    assert preview.assets[0].content_type == "image/webp"
