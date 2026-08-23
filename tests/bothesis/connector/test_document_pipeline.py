from __future__ import annotations

import ast
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from qdrant_client import models as qmodels

from bothesis.connector.file import FileProcessingError
from bothesis.connector.protocol import (
    AccessPolicy,
    Chunk,
    CitationInfo,
    CitationSpan,
    DocumentItem,
    DocumentKind,
    EffectiveAccess,
    Hierarchy,
    ProviderCacheEntry,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index.raw_storage import aws_s3
from bothesis.db.models import Item, ItemUpload
from bothesis.services import (
    AuthContext,
    UploadService,
    UploadTooLargeError,
)
from bothesis.services.chat_document_source import ChatDocumentSourceService
from bothesis.document_index.indexer import (
    DocumentProcessingError,
    DocumentPipeline,
    INDEX_SCHEMA_VERSION,
    PARSER_VERSION,
    CHUNKER_VERSION,
)
from bothesis.document_index.models import ChunkContext, ContextualChunk
from bothesis.document_index import BM25_MODEL, BM25_OPTIONS, SPARSE_VECTOR_NAME
from bothesis.document_index.raw_storage import (
    ObjectStorageError,
    PresignedRequest,
    S3DocumentStorage,
    StoredObject,
)
from bothesis.document_index.vector_store import QdrantDocumentIndex
import bothesis.document_index.indexer as document_indexer


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


class _EmptyProcessor:
    def process_bytes(self, raw_bytes: bytes, **kwargs: Any) -> object:
        file_name = str(kwargs.get("file_name") or "document")
        del raw_bytes
        raise FileProcessingError(f"no text in {file_name}")

    def process_path(self, path: Path, **kwargs: Any) -> object:
        file_name = str(kwargs.get("file_name") or path.name)
        raise FileProcessingError(f"no text in {file_name}")


class _NoopDocumentSource:
    async def canonicalize(self, *args: Any, **kwargs: Any) -> object:
        raise AssertionError("canonical source was not expected")

    async def direct_file_data(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("direct source was not expected")

    async def soft_delete_raw(self, *args: Any, **kwargs: Any) -> None:
        return None

def _processor(*, direct_max_bytes: int = 20 * 1024 * 1024) -> DocumentPipeline:
    return DocumentPipeline(
        cast(Any, None),
        document_source=cast(Any, _NoopDocumentSource()),
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
    status: str = "ready",
    processing: dict[str, str] | None = None,
) -> Item:
    owner_id = uuid4()
    document = Item(
        id=uuid4(),
        item_type="document",
        document_kind="document",
        owner_user_id=owner_id,
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
    document.content_sha256 = "a" * 64
    return document


def test_routing_precedence_prefers_images_then_current_index_then_small_pdf() -> None:
    processor = _processor()
    tenant_id = uuid4()

    def route(document: Item, *, current: bool = False) -> str:
        if current:
            document.status = "ready"
            document.metadata_["processing"] = {
                "source_fingerprint": "a" * 64,
                "parser_version": PARSER_VERSION,
                "chunker_version": CHUNKER_VERSION,
                "embedding_model": _Embedder.model,
                "index_schema_version": INDEX_SCHEMA_VERSION,
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


@pytest.mark.asyncio
async def test_direct_inputs_use_signed_urls_and_replay_cached_pdf_annotations() -> (
    None
):
    storage = _SignedStorage()
    cache = _CachedProviderFile()
    processor = DocumentPipeline(
        cast(Any, None),
        document_source=ChatDocumentSourceService(
            object_storage=cast(Any, storage),
            processor=cast(Any, _EmptyProcessor()),
        ),
        embedder=_Embedder(),
        vector_index=_NoopVectorIndex(),
        provider_cache=cache,
    )
    image = _document("image/png")
    image.storage_key = "users/u/documents/image/raw"

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
    pdf.storage_key = "users/u/documents/pdf/raw"

    context, _ = await processor._prepare_direct(pdf)

    assert context.content_block is None
    assert context.provider_annotations == (annotation,)
    assert storage.downloads == 1


def test_upload_limits_reject_oversize_objects() -> None:
    uploads = UploadService(
        cast(Any, None),
        object_storage=cast(Any, _SignedStorage()),
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
            checksum_sha256=hashlib.sha256(self.content).hexdigest(),
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
            citation=CitationInfo(
                spans=(CitationSpan(element_id="doc_para_001"),)
            ),
        )
        return SimpleNamespace(
            item=item,
            chunks=(chunk,),
            sha256=hashlib.sha256(self.content).hexdigest(),
        )


@pytest.mark.asyncio
async def test_index_processing_streams_object_storage_to_a_temporary_path() -> None:
    raw = b"bounded source content"
    storage = _StreamingStorage(raw)
    source_processor = _PathProcessor()
    service = ChatDocumentSourceService(
        object_storage=cast(Any, storage),
        processor=cast(Any, source_processor),
    )
    document = _document("text/plain", size_bytes=len(raw))
    document.storage_key = "tenant/document/raw"

    processed = await service.canonicalize(
        document,
        access=_access(document.owner_user_id, uuid4()),
    )

    assert storage.downloads == 1
    assert storage.reads == 0
    assert source_processor.content == raw
    assert processed.chunks[0].chunk_text == "streamed evidence"
    assert processed.source_fingerprint == hashlib.sha256(raw).hexdigest()


@pytest.mark.asyncio
async def test_index_processing_rejects_oversize_source_before_download() -> None:
    storage = _StreamingStorage(b"oversize")
    service = ChatDocumentSourceService(
        object_storage=cast(Any, storage),
        processor=cast(Any, _PathProcessor()),
        max_processing_bytes=4,
    )
    document = _document("text/plain", size_bytes=8)
    document.storage_key = "tenant/document/raw"

    with pytest.raises(DocumentProcessingError, match="processing limit"):
        await service.canonicalize(
            document,
            access=_access(document.owner_user_id, uuid4()),
        )

    assert storage.downloads == 0
    assert storage.reads == 0


@pytest.mark.asyncio
async def test_index_processing_rejects_a_processor_checksum_mismatch() -> None:
    raw = b"bounded source content"
    storage = _StreamingStorage(raw)

    class _MismatchedProcessor(_PathProcessor):
        def process_path(self, path: Path, **kwargs: Any) -> object:
            processed = cast(Any, super().process_path(path, **kwargs))
            processed.sha256 = "0" * 64
            return processed

    service = ChatDocumentSourceService(
        object_storage=cast(Any, storage),
        processor=cast(Any, _MismatchedProcessor()),
    )
    document = _document("text/plain", size_bytes=len(raw))
    document.storage_key = "tenant/document/raw"

    with pytest.raises(DocumentProcessingError, match="checksum"):
        await service.canonicalize(
            document,
            access=_access(document.owner_user_id, uuid4()),
        )


def test_document_indexer_has_no_raw_processing_implementation_dependencies() -> None:
    source_path = Path(cast(str, document_indexer.__file__))
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
            (
                "bothesis.connector.file",
                "bothesis.connector.processing",
                "bothesis.document_index.raw_storage",
            )
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

    stored = storage.put_path(
        path,
        "files/document-1/report.txt",
        content_type="text/plain",
    )

    assert client.uploaded_body == b"raw document"
    assert client.parameters["Bucket"] == "documents"
    assert client.parameters["Key"] == "files/document-1/report.txt"
    assert stored.checksum_sha256 == hashlib.sha256(b"raw document").hexdigest()


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
async def test_s3_download_to_path_streams_and_hashes_content(tmp_path: Path) -> None:
    client = _ReadingS3Client(b"streamed content")
    storage = S3DocumentStorage(bucket="documents", client=client)
    destination = tmp_path / "downloaded.bin"

    stored = await storage.download_to_path(
        "documents/id/raw",
        destination,
        max_bytes=100,
    )

    assert destination.read_bytes() == b"streamed content"
    assert stored.checksum_sha256 == hashlib.sha256(b"streamed content").hexdigest()
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
        ContextualChunk(
            id=f"{document.id}:0",
            item_id=str(document.id),
            chunk_index=0,
            content_type="text",
            chunk_text="grounded content",
            contextual_text="Document: sample\n\ngrounded content",
            context=ChunkContext(section_path=["Summary"]),
            title="sample",
            document_kind="document",
            source=SourceIdentity(
                connector_id="upload",
                provider=SourceProvider.FILE,
                external_id=str(document.id),
            ),
            hierarchy=Hierarchy(),
            access=EffectiveAccess(reader_ids=[str(user_id)]),
            citation=CitationInfo(
                section="Summary",
                section_path=("Summary",),
                spans=(CitationSpan(element_id="doc_para_001"),),
            ),
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
    vectors = store.batches[0][0].vector
    assert vectors["content"] == [0.1, 0.2]
    assert vectors[SPARSE_VECTOR_NAME] == qmodels.Document(
        text=chunks[0].contextual_text,
        model=BM25_MODEL,
        options=BM25_OPTIONS,
    )
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
    entry = ProviderCacheEntry(
        provider="openrouter",
        source_fingerprint="a" * 64,
        reference={"file_id": "file-123"},
        expires_at=datetime(2000, 1, 1, tzinfo=UTC),
    )

    assert entry.is_expired
