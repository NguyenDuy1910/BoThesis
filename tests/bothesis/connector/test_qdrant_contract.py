from __future__ import annotations

import json

import pytest
from bothesis.connector.protocol import (
    AccessPolicy,
    Chunk,
    CitationInfo,
    CitationSpan,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
    TextPart,
)
from bothesis.document_index import (
    INDEX_SCHEMA_VERSION,
    ContextualChunk,
    IndexingContext,
    ItemIndex,
    build_contextual_chunks,
)


def _document() -> DocumentItem:
    return DocumentItem(
        id="jira::BANK-42",
        title="Story: Lending policy",
        document_kind=DocumentKind.ISSUE,
        source=SourceIdentity(
            connector_id="connection-1",
            provider=SourceProvider.JIRA,
            external_id="BANK-42",
            url="https://jira.example/browse/BANK-42",
        ),
        hierarchy=Hierarchy(parent_id="jira::BANK"),
        metadata={"summary": "Explains the approved lending policy."},
        access=AccessPolicy.from_reader_ids(["public"]),
        content=[TextPart(text="RAW-CONTENT-MUST-NOT-BE-INDEXED")],
    )


def _chunk() -> Chunk:
    return Chunk(
        id="jira::BANK-42:0",
        item_id="jira::BANK-42",
        chunk_index=0,
        chunk_text="connector evidence",
        content_type="mixed",
        citation=CitationInfo(
            section="Replication",
            spans=(CitationSpan(page=2), CitationSpan(page=4)),
        ),
    )


def _context() -> IndexingContext:
    return IndexingContext(
        tenant_id="tenant-1",
        collection_item_id="collection-1",
        document_type="jira_issue",
        connector_key="jira",
    )


class _Embedder:
    embedding_model = "test-embedding"

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        return [[float(len(document))] for document in documents]


class _Backend:
    def __init__(self) -> None:
        self.records: list[object] = []

    async def replace_item_points(self, **kwargs: object) -> None:
        self.records = list(kwargs["records"])  # type: ignore[arg-type]


def test_indexing_context_normalizes_required_identifiers() -> None:
    context = IndexingContext(
        tenant_id=" tenant-1 ",
        collection_item_id=" collection-1 ",
        parent_item_id=" ",
        document_type=" plain_text ",
        connector_key=" file ",
    )

    assert context.tenant_id == "tenant-1"
    assert context.collection_item_id == "collection-1"
    assert context.parent_item_id is None
    assert context.document_type == "plain_text"
    assert context.connector_key == "file"


@pytest.mark.asyncio
async def test_index_projection_is_bounded_and_collection_scoped() -> None:
    document = _document()
    source_chunk = _chunk()
    contextual = await build_contextual_chunks([source_chunk], document)
    assert len(contextual) == 1
    assert isinstance(contextual[0], ContextualChunk)
    assert contextual[0].chunk_text == source_chunk.chunk_text
    assert "RAW-CONTENT-MUST-NOT-BE-INDEXED" not in contextual[0].contextual_text
    backend = _Backend()
    index = ItemIndex(backend=backend, embedder=_Embedder())  # type: ignore[arg-type]
    await index.index_item_content(document, [source_chunk], context=_context())
    record = backend.records[0]
    assert hasattr(record, "payload")
    payload = record.payload
    assert payload.collection_item_id == "collection-1"
    assert payload.connector_key == "jira"
    assert payload.section_path == ["Replication"]
    assert payload.page_start == 2
    assert payload.page_end == 4
    assert payload.schema_version == INDEX_SCHEMA_VERSION
    serialized_payload = payload.to_payload()
    assert {
        "integration_connection_id",
        "ingestion_source_id",
        "embedding_model",
        "root_id",
        "context_section_path",
        "citation_section_path",
        "citation_section",
        "context_summary",
        "citation_spans",
    }.isdisjoint(serialized_payload)
    serialized = json.dumps(serialized_payload)
    assert "RAW-CONTENT-MUST-NOT-BE-INDEXED" not in serialized


@pytest.mark.asyncio
async def test_qdrant_point_ids_are_deterministic() -> None:
    backend = _Backend()
    index = ItemIndex(backend=backend, embedder=_Embedder())  # type: ignore[arg-type]
    await index.index_item_content(_document(), [_chunk()], context=_context())
    first_id = backend.records[0].point_id
    await index.index_item_content(_document(), [_chunk()], context=_context())
    assert backend.records[0].point_id == first_id


def test_public_access_is_explicit() -> None:
    assert AccessPolicy().is_public is False
    assert AccessPolicy.from_reader_ids(["public"]).is_public is True


@pytest.mark.asyncio
async def test_index_boundary_rejects_chunks_from_another_document() -> None:
    with pytest.raises(ValueError, match="belongs to item"):
        await build_contextual_chunks(
            [_chunk().model_copy(update={"item_id": "another-item"})],
            _document(),
        )


class _SemanticContextualizer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def describe(self, chunk: Chunk, **kwargs: object) -> str:
        self.calls.append({"chunk": chunk, **kwargs})
        if self.fail:
            raise RuntimeError("semantic provider failed")
        return "The chunk describes the BANK-42 approved lending policy."


@pytest.mark.asyncio
async def test_semantic_contextualization_enriches_retrieval_not_evidence() -> None:
    contextualizer = _SemanticContextualizer()
    source = _chunk()

    contextual = await build_contextual_chunks(
        [source],
        _document(),
        semantic_contextualizer=contextualizer,  # type: ignore[arg-type]
    )

    assert len(contextualizer.calls) == 1
    call = contextualizer.calls[0]
    assert "Document: Story: Lending policy" in str(call["document_context"])
    assert "RAW-CONTENT-MUST-NOT-BE-INDEXED" not in str(call["document_context"])
    assert contextual[0].chunk_text == "connector evidence"
    assert "BANK-42 approved lending policy" in contextual[0].contextual_text
    assert contextual[0].contextual_text.endswith(source.chunk_text)


@pytest.mark.asyncio
async def test_semantic_contextualization_failure_uses_structural_fallback() -> None:
    contextualizer = _SemanticContextualizer(fail=True)

    contextual = await build_contextual_chunks(
        [_chunk()],
        _document(),
        semantic_contextualizer=contextualizer,  # type: ignore[arg-type]
    )

    assert len(contextualizer.calls) == 1
    assert contextual[0].chunk_text == "connector evidence"
    assert "Explains the approved lending policy." in contextual[0].contextual_text
