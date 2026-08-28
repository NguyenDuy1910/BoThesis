from __future__ import annotations

import json

import pytest

from bothesis.connector.protocol import (
    AccessPolicy,
    CitationInfo,
    Chunk,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
    TextPart,
)
from bothesis.document_index import INDEX_SCHEMA_VERSION
from bothesis.document_index.models import ContextualChunk
from bothesis.document_index.payload import (
    QdrantPayloadContext,
    build_contextual_chunks,
    build_qdrant_records,
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
        citation=CitationInfo(section="Replication"),
    )


def _context() -> QdrantPayloadContext:
    return QdrantPayloadContext(
        tenant_id="tenant-1",
        connection_id="connection-1",
        binding_id="binding-1",
        collection_item_id="collection-1",
        document_type="jira_issue",
        plugin_key="jira",
        embedding_model="embed-v1",
    )


@pytest.mark.asyncio
async def test_index_projection_is_bounded_and_collection_scoped() -> None:
    document = _document()
    source_chunk = _chunk()
    contextual = await build_contextual_chunks([source_chunk], document)
    assert len(contextual) == 1
    assert isinstance(contextual[0], ContextualChunk)
    assert contextual[0].chunk_text == source_chunk.chunk_text
    assert "RAW-CONTENT-MUST-NOT-BE-INDEXED" not in contextual[0].contextual_text
    record = (await build_qdrant_records([source_chunk], document, _context()))[0]
    payload = record.payload
    assert payload.collection_item_id == "collection-1"
    assert payload.connection_id == "connection-1"
    assert payload.binding_id == "binding-1"
    assert payload.plugin_key == "jira"
    assert payload.schema_version == INDEX_SCHEMA_VERSION
    serialized = json.dumps(payload.for_qdrant())
    assert "RAW-CONTENT-MUST-NOT-BE-INDEXED" not in serialized


@pytest.mark.asyncio
async def test_qdrant_point_ids_are_deterministic() -> None:
    first = await build_qdrant_records([_chunk()], _document(), _context())
    second = await build_qdrant_records([_chunk()], _document(), _context())
    assert first[0].point_id == second[0].point_id


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
