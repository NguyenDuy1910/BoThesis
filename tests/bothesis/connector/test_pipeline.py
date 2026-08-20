from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from bothesis.connector.base import BaseSourceConnector
from bothesis.connector.models import (
    ConnectorCheckpoint,
    ConnectorScope,
    DocumentSource,
    HierarchyNode,
    HierarchyNodeType,
    SourceACL,
    SourceChange,
    SourceChangeType,
    SourceCheckpoint,
    SourceDocument,
    TextSection,
)
from bothesis.connector.pipeline import ConnectorPipeline, ConnectorPipelineConfig
from bothesis.connector.qdrant import ChunkingConfig, QdrantChunkRecord, QdrantPayloadContext


class RecordingSink:
    def __init__(self) -> None:
        self.write_batches: list[list[QdrantChunkRecord]] = []
        self.deletes: list[tuple[str, str | int, str]] = []

    async def write(self, records: Sequence[QdrantChunkRecord]) -> int:
        self.write_batches.append(list(records))
        return len(records)

    async def soft_delete_document(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        document_id: str,
    ) -> None:
        self.deletes.append((tenant_id, connector_id, document_id))


class StubConnector(BaseSourceConnector):
    source = "file"
    checkpoint_model = SourceCheckpoint

    def __init__(self, *, fail_document: str | None = None) -> None:
        self.fail_document = fail_document
        self.active_fetches = 0
        self.max_active_fetches = 0
        self._next = SourceCheckpoint(cursor="complete")

    async def test_connection(self) -> bool:
        return True

    async def list_scopes(self) -> list[ConnectorScope]:
        return [SCOPE]

    async def discover_changes(
        self, checkpoint: ConnectorCheckpoint, scope: ConnectorScope
    ) -> list[SourceChange]:
        del checkpoint, scope
        return [
            SourceChange(external_id="doc-1", external_version="v1"),
            SourceChange(external_id="doc-2", external_version="v2"),
            SourceChange(external_id="doc-old", change_type=SourceChangeType.DELETE),
            SourceChange(external_id="doc-1", external_version="v1"),
        ]

    async def fetch_document(self, external_id: str) -> SourceDocument:
        self.active_fetches += 1
        self.max_active_fetches = max(self.max_active_fetches, self.active_fetches)
        try:
            await asyncio.sleep(0.01)
            if external_id == self.fail_document:
                raise RuntimeError("source failed")
            return SourceDocument(
                external_id=external_id,
                source=DocumentSource.FILE,
                semantic_identifier=external_id,
                sections=[TextSection(text=external_id + " " + "x" * 150)],
                acl=SourceACL(),
            )
        finally:
            self.active_fetches -= 1

    async def fetch_acl(self, external_id: str) -> SourceACL:
        del external_id
        return SourceACL(user_group_ids={"staff"})

    async def fetch_hierarchy(self, scope: ConnectorScope) -> list[HierarchyNode]:
        del scope
        return [
            HierarchyNode(
                raw_node_id="root",
                display_name="Root",
                node_type=HierarchyNodeType.FOLDER,
            )
        ]

    def next_checkpoint(self) -> ConnectorCheckpoint:
        return self._next


SCOPE = ConnectorScope(scope_type="folder", scope_value="root", display_name="Root")
CONTEXT = QdrantPayloadContext(tenant_id="tenant-1", connector_id="connector-1")


@pytest.mark.asyncio
async def test_pipeline_batches_payloads_bounds_fetches_and_advances_checkpoint() -> None:
    connector = StubConnector()
    sink = RecordingSink()
    pipeline = ConnectorPipeline(
        connector,
        sink,
        context=CONTEXT,
        config=ConnectorPipelineConfig(
            fetch_concurrency=2,
            payload_batch_size=2,
            chunking=ChunkingConfig(max_characters=100, overlap_characters=0),
        ),
    )

    result = await pipeline.run_scope(SCOPE, SourceCheckpoint())

    assert result.discovered_changes == 3
    assert result.processed_documents == 2
    assert result.written_chunks == 4
    assert result.deleted_documents == 1
    assert result.replaced_documents == 2
    assert result.checkpoint_advanced is True
    assert result.checkpoint == SourceCheckpoint(cursor="complete")
    assert connector.max_active_fetches == 2
    assert [len(batch) for batch in sink.write_batches] == [2, 2]
    assert sink.deletes == [
        ("tenant-1", "connector-1", "doc-old"),
        ("tenant-1", "connector-1", "doc-2"),
        ("tenant-1", "connector-1", "doc-1"),
    ]
    assert result.hierarchy[0].raw_node_id == "root"
    assert all(
        record.payload.access_control_list == ["external_group:staff"]
        for batch in sink.write_batches
        for record in batch
    )


@pytest.mark.asyncio
async def test_pipeline_does_not_advance_checkpoint_after_partial_failure() -> None:
    initial = SourceCheckpoint(cursor="before")
    connector = StubConnector(fail_document="doc-2")
    sink = RecordingSink()
    pipeline = ConnectorPipeline(
        connector,
        sink,
        context=CONTEXT,
        config=ConnectorPipelineConfig(
            continue_on_error=True,
            fetch_hierarchy=False,
            chunking=ChunkingConfig(max_characters=100, overlap_characters=0),
        ),
    )

    result = await pipeline.run_scope(SCOPE, initial)

    assert result.checkpoint_advanced is False
    assert result.checkpoint == initial
    assert result.processed_documents == 1
    assert result.failures[0].external_id == "doc-2"
    assert result.failures[0].operation == "fetch"
