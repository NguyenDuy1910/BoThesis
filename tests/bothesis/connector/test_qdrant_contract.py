from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from bothesis.connector.protocol import (
    AccessPolicy,
    BoundingBox,
    Chunk,
    CitationInfo,
    CitationSpan,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
    StorageObject,
    TextPart,
)
from bothesis.document_index.embedding import embedding_texts
from bothesis.document_index.connector_sink import QdrantConnectorIndexSink
from bothesis.document_index.models import ContextualChunk
from bothesis.document_index.payload import (
    QdrantPayloadContext,
    build_contextual_chunks,
    build_qdrant_records,
)


def _document(*, source_url: str = "https://jira.example/browse/BANK-42") -> DocumentItem:
    return DocumentItem(
        id="jira::BANK-42",
        title="Story: Lending policy",
        document_kind=DocumentKind.ISSUE,
        source=SourceIdentity(
            connector_id="connector-1",
            provider=SourceProvider.JIRA,
            external_id="BANK-42",
            external_version="7",
            etag="etag-7",
            url=source_url,
        ),
        hierarchy=Hierarchy(
            parent_id="jira::BANK",
            root_id="jira::root",
            ancestor_ids=["jira::root", "jira::BANK"],
        ),
        metadata={
            "summary": "Explains the approved lending policy.",
            "provider_private_metadata": "must-not-be-indexed",
        },
        access=AccessPolicy.from_reader_ids(
            ["email:Analyst@Example.com", "external_group:Risk-Team"]
        ),
        # The index boundary must not derive chunks from raw content parts.
        content=[TextPart(text="RAW-CONTENT-MUST-NOT-BE-INDEXED")],
    )


def _chunk(
    *,
    chunk_id: str = "jira::BANK-42:4",
    item_id: str = "jira::BANK-42",
    chunk_index: int = 4,
    chunk_text: str = "  connector evidence\n" + ("A" * 5_000),
) -> Chunk:
    return Chunk(
        id=chunk_id,
        item_id=item_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        content_type="mixed",
        section_path=["Reliability", "Replication"],
        citation=CitationInfo(
            section="Replication",
            section_path=("Reliability", "Replication"),
            anchor="replication",
            spans=(
                CitationSpan(
                    page=120,
                    element_id="p120_para18",
                    start_offset=3,
                    end_offset=22,
                ),
                CitationSpan(
                    page=121,
                    element_id="p121_image01",
                    start_offset=0,
                    end_offset=17,
                    bounding_box=BoundingBox(x=0.1, y=0.2, width=0.5, height=0.4),
                ),
            ),
        ),
    )


def _context() -> QdrantPayloadContext:
    return QdrantPayloadContext(
        tenant_id="tenant-1",
        connector_id="connector-1",
        scope_id="scope-1",
        embedding_model="embed-v1",
    )


def test_index_projection_starts_from_connector_chunk_and_is_bounded() -> None:
    document = _document()
    source_chunk = _chunk()

    contextual = build_contextual_chunks([source_chunk], document)

    assert len(contextual) == 1
    assert isinstance(contextual[0], ContextualChunk)
    assert contextual[0].chunk_text == source_chunk.chunk_text
    assert contextual[0].citation == source_chunk.citation
    assert contextual[0].context.section_path == source_chunk.section_path
    assert contextual[0].context.summary == "Explains the approved lending policy."
    assert contextual[0].contextual_text.endswith(source_chunk.chunk_text)
    assert "Document: Story: Lending policy" in contextual[0].contextual_text
    assert "Section: Reliability > Replication" in contextual[0].contextual_text

    # Embedding input is enriched retrieval text, never the evidence-only text.
    assert embedding_texts(contextual) == [contextual[0].contextual_text]
    assert embedding_texts(contextual) != [source_chunk.chunk_text]

    records = build_qdrant_records([source_chunk], document, _context())

    # A connector chunk remains one point even when it exceeds the former
    # document-index character limit.
    assert len(records) == 1
    payload = records[0].payload
    assert payload.chunk_id == source_chunk.id
    assert payload.chunk_index == 4
    assert payload.chunk_text == source_chunk.chunk_text
    assert payload.contextual_text == contextual[0].contextual_text
    assert payload.reader_ids == [
        "email:analyst@example.com",
        "external_group:risk-team",
    ]
    assert payload.parent_id == "jira::BANK"
    assert payload.root_id == "jira::root"
    assert payload.ancestor_ids == ["jira::root", "jira::BANK"]
    assert payload.citation_section == "Replication"
    assert payload.citation_section_path == ["Reliability", "Replication"]
    assert payload.citation_anchor == "replication"
    assert payload.citation_spans == source_chunk.citation.spans
    assert payload.page_start == 120
    assert payload.page_end == 121
    assert payload.source_url == "https://jira.example/browse/BANK-42"
    assert payload.embedding_model == "embed-v1"

    serialized = payload.for_qdrant()
    serialized_text = json.dumps(serialized)
    assert "RAW-CONTENT-MUST-NOT-BE-INDEXED" not in serialized_text
    assert "must-not-be-indexed" not in serialized_text
    assert {"access", "content", "metadata", "storage"}.isdisjoint(serialized)
    restored = type(payload).model_validate(serialized)
    assert restored.citation_spans == source_chunk.citation.spans


def test_qdrant_point_ids_are_deterministic_for_canonical_chunk_indexes() -> None:
    document = _document()
    chunks = [
        _chunk(),
        _chunk(
            chunk_id="jira::BANK-42:9",
            chunk_index=9,
            chunk_text="second connector chunk",
        ),
    ]

    first = build_qdrant_records(chunks, document, _context())
    repeated = build_qdrant_records(list(reversed(chunks)), document, _context())

    first_ids = {record.payload.chunk_id: record.point_id for record in first}
    repeated_ids = {record.payload.chunk_id: record.point_id for record in repeated}
    assert first_ids == repeated_ids
    assert len(set(first_ids.values())) == 2


@pytest.mark.parametrize(
    ("chunks", "message"),
    [
        ([], "has no connector chunks"),
        ([_chunk(item_id="another-item")], "belongs to item"),
        (
            [
                _chunk(),
                _chunk(chunk_id="jira::BANK-42:other", chunk_index=4),
            ],
            "Duplicate chunk index",
        ),
        (
            [
                _chunk(),
                _chunk(chunk_id="jira::BANK-42:4", chunk_index=5),
            ],
            "Duplicate chunk id",
        ),
    ],
)
def test_index_boundary_rejects_invalid_chunk_identity(
    chunks: list[Chunk],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_contextual_chunks(chunks, _document())


def test_presigned_source_url_is_never_persisted() -> None:
    document = _document(
        source_url=(
            "https://objects.example.test/raw.pdf"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=secret"
        )
    )

    payload = build_qdrant_records([_chunk()], document, _context())[0].payload

    assert payload.source_url is None
    assert "X-Amz-Signature" not in str(payload.for_qdrant())
    assert "secret" not in str(payload.for_qdrant())


def test_public_acl_is_explicit_not_implicit() -> None:
    private = AccessPolicy()
    public = AccessPolicy.from_reader_ids(["public"])

    assert private.to_reader_ids() == []
    assert public.to_reader_ids() == ["public"]


class _RecordingEmbedder:
    model = "embed-v1"

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        self.batches.append(list(documents))
        return [[float(len(document))] for document in documents]


class _RecordingStore:
    def __init__(self) -> None:
        self.points: list[object] = []
        self.deleted_payload: dict[str, object] | None = None
        self.deleted_filter: object | None = None
        self.payload_calls: list[tuple[dict[str, object], object]] = []

    async def upsert_points(self, points: list[object]) -> None:
        self.points = list(points)

    async def set_payload(self, *, payload: dict[str, object], points: object) -> None:
        self.deleted_payload = payload
        self.deleted_filter = points
        self.payload_calls.append((dict(payload), points))

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_connector_sink_runs_the_canonical_vertical_index_flow() -> None:
    store = _RecordingStore()
    embedder = _RecordingEmbedder()
    sink = QdrantConnectorIndexSink(
        store,  # type: ignore[arg-type]
        embedder,  # type: ignore[arg-type]
        embedding_batch_size=1,
    )
    document = _document()
    source_chunk = _chunk()

    written = await sink.write(
        document,
        [source_chunk],
        tenant_id="tenant-1",
        connector_id="connector-1",
    )

    assert written == 1
    assert len(embedder.batches) == 1
    assert embedder.batches[0][0].endswith(source_chunk.chunk_text)
    point = store.points[0]
    assert getattr(point, "vector") == {
        "content": [float(len(embedder.batches[0][0]))]
    }
    payload = getattr(point, "payload")
    assert payload["chunk_text"] == source_chunk.chunk_text
    assert payload["citation_spans"][1]["element_id"] == "p121_image01"
    assert payload["reader_ids"] == [
        "email:analyst@example.com",
        "external_group:risk-team",
    ]

    await sink.soft_delete_item(
        tenant_id="tenant-1",
        connector_id="connector-1",
        item_id=document.id,
    )

    assert store.deleted_payload == {"is_deleted": True, "reader_ids": []}
    conditions = getattr(store.deleted_filter, "must")
    assert [condition.key for condition in conditions] == [
        "tenant_id",
        "connector_id",
        "item_id",
    ]


class _Transaction:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


class _SessionFactory:
    def begin(self) -> _Transaction:
        return _Transaction()


class _RecordingDocumentService:
    calls: list[tuple[str, object]] = []
    document_id = uuid4()

    def __init__(self, session: object) -> None:
        del session

    async def upsert_external_document(
        self,
        scope_id: int,
        generation: int,
        external_id: str,
        **values: object,
    ) -> object:
        self.calls.append(
            (
                "upsert",
                {
                    "scope_id": scope_id,
                    "generation": generation,
                    "external_id": external_id,
                    **values,
                },
            )
        )
        return SimpleNamespace(id=self.document_id, tenant_id="tenant-1")

    async def replace_chunks(self, document_id: object, chunks: object) -> None:
        self.calls.append(("chunks", (document_id, chunks)))

    async def soft_delete_chunks(self, document_id: object) -> None:
        self.calls.append(("empty", document_id))

    async def mark_indexed(
        self,
        document_id: object,
        *,
        allow_empty: bool = False,
    ) -> None:
        self.calls.append(("indexed", (document_id, allow_empty)))

    async def mark_index_failed(self, document_id: object) -> None:
        self.calls.append(("failed", document_id))


@pytest.mark.asyncio
async def test_persistent_connector_sink_stages_canonical_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bothesis.services.DocumentService",
        _RecordingDocumentService,
    )
    _RecordingDocumentService.calls.clear()
    store = _RecordingStore()
    sink = QdrantConnectorIndexSink(
        store,  # type: ignore[arg-type]
        _RecordingEmbedder(),  # type: ignore[arg-type]
        session_factory=_SessionFactory(),  # type: ignore[arg-type]
        connector_scope_id=17,
        generation=3,
    )
    document = _document().model_copy(
        update={
            "original": StorageObject(
                provider="s3",
                bucket="raw-documents",
                key="tenant-1/source.pdf",
                file_name="source.pdf",
                size_bytes=2048,
                content_type="application/pdf",
                checksum_sha256="a" * 64,
            )
        }
    )

    assert await sink.write(
        document,
        [_chunk()],
        tenant_id="tenant-1",
        connector_id="connector-1",
    ) == 1

    upsert = dict(_RecordingDocumentService.calls[0][1])  # type: ignore[arg-type]
    assert upsert["scope_id"] == 17
    assert upsert["generation"] == 3
    assert upsert["raw_storage_key"] == "tenant-1/source.pdf"
    assert upsert["content_sha256"] == "a" * 64
    canonical_item = upsert["metadata"]["canonical_item"]  # type: ignore[index]
    assert canonical_item["original"]["bucket"] == "raw-documents"
    assert "url" not in canonical_item["original"]
    stored_chunks = _RecordingDocumentService.calls[1][1][1]  # type: ignore[index]
    assert stored_chunks[0].chunk_id == "jira::BANK-42:4"
    assert stored_chunks[0].citation_spans == _chunk().citation.spans
    point_payload = getattr(store.points[0], "payload")
    assert point_payload["generation"] == 3
    assert point_payload["scope_id"] == 17
    assert point_payload["is_deleted"] is True

    await sink.activate_generation(
        tenant_id="tenant-1",
        connector_id="connector-1",
    )

    assert store.payload_calls[-2][0] == {
        "is_deleted": True,
        "reader_ids": [],
    }
    assert store.payload_calls[-1][0] == {"is_deleted": False}
