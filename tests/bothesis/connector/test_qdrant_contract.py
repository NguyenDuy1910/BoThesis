from __future__ import annotations

import json
from types import SimpleNamespace
from typing import get_type_hints
from uuid import uuid4

import pytest
from qdrant_client import models as qmodels

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
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.document_index.embedding import embedding_texts
from bothesis.document_index.connector_sink import QdrantConnectorIndexSink
from bothesis.document_index import BM25_MODEL, BM25_OPTIONS, SPARSE_VECTOR_NAME
from bothesis.document_index.models import ContextualChunk
from bothesis.document_index.payload import (
    QdrantPayloadContext,
    build_contextual_chunks,
    build_qdrant_records,
)
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer


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


@pytest.mark.asyncio
async def test_index_projection_starts_from_connector_chunk_and_is_bounded() -> None:
    document = _document()
    source_chunk = _chunk()

    contextual = await build_contextual_chunks([source_chunk], document)

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

    records = await build_qdrant_records([source_chunk], document, _context())

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


class _ContextModel:
    def __init__(self, *, output: str | None = None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def responses(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output_text=self.output)


def test_semantic_contextualizer_requires_the_existing_openrouter_transport() -> None:
    annotations = get_type_hints(SemanticContextualizer.__init__)

    assert annotations["transport"] is OpenRouterTransport


@pytest.mark.asyncio
async def test_semantic_contextualizer_renders_prompt_and_normalizes_output() -> None:
    transport = _ContextModel(
        output="  This chunk describes the APAC Q2 revenue increase.  "
    )
    contextualizer = SemanticContextualizer(
        transport,  # type: ignore[arg-type]
        model_name="openai/gpt-5-mini",
    )
    chunk = _chunk(chunk_text="It increased by 17%.")
    canonical_text = chunk.chunk_text

    result = await contextualizer.describe(
        chunk,
        document_context="Q2 revenue increased across APAC markets.",
        title="Quarterly Sales Report Q2 2026",
        section_path=("Revenue", "APAC"),
    )

    assert result == "This chunk describes the APAC Q2 revenue increase."
    assert chunk.chunk_text == canonical_text
    call = transport.calls[0]
    assert call["model"] == "openai/gpt-5-mini"
    assert call["max_output_tokens"] == 128
    assert call["temperature"] == 0
    assert "instructions" not in call
    prompt = str(call["input"])
    assert "<document_title>Quarterly Sales Report Q2 2026</document_title>" in prompt
    assert "<section_path>Revenue &gt; APAC</section_path>" in prompt
    assert "<document>\nQ2 revenue increased across APAC markets.\n</document>" in prompt
    assert "<chunk>\nIt increased by 17%.\n</chunk>" in prompt


@pytest.mark.asyncio
async def test_semantic_contextualizer_treats_whitespace_as_unavailable() -> None:
    contextualizer = SemanticContextualizer(
        _ContextModel(output="  \n ")  # type: ignore[arg-type]
    )

    result = await contextualizer.describe(
        _chunk(chunk_text="Canonical evidence"),
        document_context="Document metadata",
    )

    assert result is None


@pytest.mark.asyncio
async def test_semantic_context_replaces_summary_in_retrieval_text() -> None:
    model = _ContextModel(output="This chunk explains replication reliability.")
    contextualizer = SemanticContextualizer(model)  # type: ignore[arg-type]

    contextual = await build_contextual_chunks(
        [_chunk()],
        _document(),
        semantic_contextualizer=contextualizer,
    )

    assert contextual[0].contextual_text.startswith(
        "Document: Story: Lending policy\n"
        "Section: Reliability > Replication\n"
        "Context: This chunk explains replication reliability.\n\n"
    )
    assert "Explains the approved lending policy." not in contextual[0].contextual_text
    assert contextual[0].contextual_text.endswith(_chunk().chunk_text)
    request = str(model.calls[0]["input"])
    assert "RAW-CONTENT-MUST-NOT-BE-INDEXED" not in request
    assert _chunk().chunk_text in request


@pytest.mark.asyncio
async def test_document_context_prioritizes_same_section_and_excludes_target() -> None:
    same_section = _chunk(
        chunk_id="jira::BANK-42:0",
        chunk_index=0,
        chunk_text="Vietnam and Thailand are the primary contributors.",
    )
    target = _chunk(
        chunk_id="jira::BANK-42:10",
        chunk_index=10,
        chunk_text="It increased by 17%.",
    )
    nearby = _chunk(
        chunk_id="jira::BANK-42:9",
        chunk_index=9,
        chunk_text="The EMEA segment remained flat.",
    ).model_copy(update={"section_path": ["Revenue", "EMEA"]})
    transport = _ContextModel(output="APAC revenue increased by 17%.")

    await build_contextual_chunks(
        [same_section, target, nearby],
        _document(),
        semantic_contextualizer=SemanticContextualizer(  # type: ignore[arg-type]
            transport
        ),
    )

    target_prompt = str(transport.calls[1]["input"])
    document_context = target_prompt.split("<document>\n", 1)[1].split(
        "\n</document>", 1
    )[0]
    assert "It increased by 17%." not in document_context
    assert document_context.index("primary contributors") < document_context.index(
        "EMEA segment"
    )
    assert target_prompt.count("It increased by 17%.") == 1


@pytest.mark.asyncio
async def test_document_context_is_bounded_without_truncating_target_chunk() -> None:
    target_text = "TARGET-START " + ("T" * 15_000) + " TARGET-END"
    target = _chunk(
        chunk_id="jira::BANK-42:0",
        chunk_index=0,
        chunk_text=target_text,
    )
    neighbors = [
        _chunk(
            chunk_id=f"jira::BANK-42:{index}",
            chunk_index=index,
            chunk_text=f"NEIGHBOR-{index} " + ("N" * 3_000),
        )
        for index in range(1, 9)
    ]
    transport = _ContextModel(output="Target-specific retrieval context.")

    await build_contextual_chunks(
        [target, *neighbors],
        _document(),
        semantic_contextualizer=SemanticContextualizer(  # type: ignore[arg-type]
            transport
        ),
    )

    target_prompt = str(transport.calls[0]["input"])
    document_context = target_prompt.split("<document>\n", 1)[1].split(
        "\n</document>", 1
    )[0]
    target_input = target_prompt.split("<chunk>\n", 1)[1].split("\n</chunk>", 1)[0]
    assert len(document_context) <= 12_000
    assert target_input == target_text


@pytest.mark.asyncio
async def test_semantic_context_failure_falls_back_to_document_summary() -> None:
    contextualizer = SemanticContextualizer(
        _ContextModel(error=RuntimeError("provider unavailable"))  # type: ignore[arg-type]
    )

    contextual = await build_contextual_chunks(
        [_chunk()],
        _document(),
        semantic_contextualizer=contextualizer,
    )

    assert "Context: Explains the approved lending policy." in contextual[0].contextual_text
    assert "Description:" not in contextual[0].contextual_text


@pytest.mark.asyncio
async def test_absent_optional_context_does_not_emit_empty_labels() -> None:
    document = _document().model_copy(update={"title": None, "metadata": {}})
    chunk = _chunk(chunk_text="Canonical evidence").model_copy(
        update={"section_path": []}
    )

    contextual = await build_contextual_chunks([chunk], document)

    assert contextual[0].contextual_text == "Canonical evidence"
    assert "Document:" not in contextual[0].contextual_text
    assert "Section:" not in contextual[0].contextual_text
    assert "Context:" not in contextual[0].contextual_text


@pytest.mark.asyncio
async def test_qdrant_point_ids_are_deterministic_for_canonical_chunk_indexes() -> None:
    document = _document()
    chunks = [
        _chunk(),
        _chunk(
            chunk_id="jira::BANK-42:9",
            chunk_index=9,
            chunk_text="second connector chunk",
        ),
    ]

    first = await build_qdrant_records(chunks, document, _context())
    repeated = await build_qdrant_records(
        list(reversed(chunks)), document, _context()
    )

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
@pytest.mark.asyncio
async def test_index_boundary_rejects_invalid_chunk_identity(
    chunks: list[Chunk],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await build_contextual_chunks(chunks, _document())


@pytest.mark.asyncio
async def test_presigned_source_url_is_never_persisted() -> None:
    document = _document(
        source_url=(
            "https://objects.example.test/raw.pdf"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=secret"
        )
    )

    payload = (await build_qdrant_records([_chunk()], document, _context()))[0].payload

    assert payload.source_url is None
    assert "X-Amz-Signature" not in str(payload.for_qdrant())
    assert "secret" not in str(payload.for_qdrant())


def test_public_acl_is_explicit_not_implicit() -> None:
    private = AccessPolicy()
    public = AccessPolicy.from_reader_ids(["public"])

    assert private.to_reader_ids() == []
    assert public.to_reader_ids() == ["public"]


@pytest.mark.asyncio
async def test_qdrant_payload_projects_explicit_denied_principals() -> None:
    context = _context().model_copy(
        update={"denied_reader_ids": ["group:blocked", "group:blocked"]}
    )

    payload = (await build_qdrant_records([_chunk()], _document(), context))[0].payload

    assert payload.denied_reader_ids == ["group:blocked"]


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
    document = _document().model_copy(
        update={"source": _document().source.model_copy(update={"connector_id": "1"})}
    )
    source_chunk = _chunk()

    written = await sink.write(
        document,
        [source_chunk],
        tenant_id="tenant-1",
        connector_id=1,
    )

    assert written == 1
    assert len(embedder.batches) == 1
    assert embedder.batches[0][0].endswith(source_chunk.chunk_text)
    point = store.points[0]
    vectors = getattr(point, "vector")
    assert vectors["content"] == [float(len(embedder.batches[0][0]))]
    sparse = vectors[SPARSE_VECTOR_NAME]
    assert sparse == qmodels.Document(
        text=embedder.batches[0][0],
        model=BM25_MODEL,
        options=BM25_OPTIONS,
    )
    payload = getattr(point, "payload")
    assert payload["chunk_text"] == source_chunk.chunk_text
    assert payload["citation_spans"][1]["element_id"] == "p121_image01"
    assert payload["reader_ids"] == [
        "email:analyst@example.com",
        "external_group:risk-team",
    ]

    await sink.soft_delete_item(
        tenant_id="tenant-1",
        connector_id=1,
        item_id=document.id,
    )

    assert store.deleted_payload == {
        "is_deleted": True,
        "reader_ids": [],
        "denied_reader_ids": [],
    }
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


class _RecordingItemService:
    calls: list[tuple[str, object]] = []
    item_id = uuid4()

    def __init__(self, session: object) -> None:
        del session

    @staticmethod
    def connector_item_id(connector_id: int, item_id: str):
        from bothesis.services.item import ItemService

        return ItemService.connector_item_id(connector_id, item_id)

    async def upsert_external_item(
        self,
        scope_id: int,
        external_id: str,
        **values: object,
    ) -> object:
        self.calls.append(
            (
                "upsert",
                {
                    "scope_id": scope_id,
                    "external_id": external_id,
                    **values,
                },
            )
        )
        return SimpleNamespace(id=self.item_id, tenant_id="tenant-1")

    async def mark_ready(self, item_id: object) -> None:
        self.calls.append(("ready", item_id))

    async def mark_failed(self, item_id: object) -> None:
        self.calls.append(("failed", item_id))


@pytest.mark.asyncio
async def test_persistent_connector_sink_stores_item_and_indexes_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bothesis.services.ItemService",
        _RecordingItemService,
    )
    _RecordingItemService.calls.clear()
    store = _RecordingStore()
    sink = QdrantConnectorIndexSink(
        store,  # type: ignore[arg-type]
        _RecordingEmbedder(),  # type: ignore[arg-type]
        session_factory=_SessionFactory(),  # type: ignore[arg-type]
        connector_scope_id=17,
    )
    document = _document().model_copy(
        update={
            "source": _document().source.model_copy(update={"connector_id": "7"}),
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
        connector_id=7,
    ) == 1

    upsert = dict(_RecordingItemService.calls[0][1])  # type: ignore[arg-type]
    assert upsert["scope_id"] == 17
    assert upsert["external_id"] == "BANK-42"
    assert upsert["item_type"] == "document"
    assert upsert["storage_key"] == "tenant-1/source.pdf"
    assert upsert["content_sha256"] == "a" * 64
    assert "canonical_item" not in upsert["metadata"]  # type: ignore[operator]
    assert "raw-documents" not in json.dumps(upsert["metadata"])
    assert _RecordingItemService.calls[-1] == (
        "ready",
        _RecordingItemService.item_id,
    )
    point_payload = getattr(store.points[0], "payload")
    assert "generation" not in point_payload
    assert "raw_storage_key" not in point_payload
    assert point_payload["scope_id"] == 17
    assert point_payload["is_deleted"] is False
    assert store.payload_calls == [
        (
            {
                "is_deleted": True,
                "reader_ids": [],
                "denied_reader_ids": [],
            },
            store.deleted_filter,
        )
    ]
