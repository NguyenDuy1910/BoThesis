from __future__ import annotations

import asyncio
from collections.abc import Sequence
import pytest

from bothesis.connector.base import BaseSourceConnector
from bothesis.connector.protocol import (
    AnyItem,
    Chunk,
    CitationInfo,
    CitationSpan,
    ConnectorCheckpoint,
    ConnectorScope,
    SourceCheckpoint,
)
from bothesis.connector.pipeline import ConnectorPipeline, ConnectorPipelineConfig
from bothesis.connector.protocol import (
    AccessPolicy,
    ChangeType,
    CollectionItem,
    CollectionKind,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    ItemChange,
    SourceIdentity,
    SourceProvider,
    TextPart,
)


class RecordingSink:
    def __init__(self) -> None:
        self.items: list[AnyItem] = []
        self.writes: list[tuple[DocumentItem, tuple[Chunk, ...]]] = []
        self.deletes: list[tuple[str, str | int, str]] = []

    async def write_item(
        self,
        item: AnyItem,
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> object:
        del tenant_id, connector_id
        self.items.append(item)
        return item.id

    async def write(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> int:
        del tenant_id, connector_id
        self.writes.append((item, tuple(chunks)))
        return len(chunks)

    async def soft_delete_item(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        item_id: str,
    ) -> None:
        self.deletes.append((tenant_id, connector_id, item_id))


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
    ) -> list[ItemChange]:
        del checkpoint, scope
        return [
            ItemChange(type=ChangeType.UPSERT, item_id="doc-1"),
            ItemChange(type=ChangeType.UPSERT, item_id="doc-2"),
            ItemChange(type=ChangeType.DELETE, item_id="doc-old"),
            ItemChange(type=ChangeType.UPSERT, item_id="doc-1"),
        ]

    async def fetch_item(self, external_id: str) -> DocumentItem:
        self.active_fetches += 1
        self.max_active_fetches = max(self.max_active_fetches, self.active_fetches)
        try:
            await asyncio.sleep(0.01)
            if external_id == self.fail_document:
                raise RuntimeError("source failed")
            return DocumentItem(
                id=external_id,
                title=external_id,
                document_kind=DocumentKind.DOCUMENT,
                source=SourceIdentity(
                    connector_id="connector-1",
                    provider=SourceProvider.FILE,
                    external_id=external_id,
                    external_version="v1",
                ),
                hierarchy=Hierarchy(parent_id="root"),
                access=AccessPolicy.from_reader_ids(["external_group:staff"]),
                content=[TextPart(text=external_id + " " + "x" * 150)],
            )
        finally:
            self.active_fetches -= 1

    async def fetch_hierarchy(self, scope: ConnectorScope) -> list[CollectionItem]:
        del scope
        return [
            CollectionItem(
                id="root",
                title="Root",
                collection_kind=CollectionKind.FOLDER,
                source=SourceIdentity(
                    connector_id="connector-1",
                    provider=SourceProvider.FILE,
                    external_id="root",
                ),
            )
        ]

    def next_checkpoint(self) -> ConnectorCheckpoint:
        return self._next


class StubChunker:
    def chunk_item(self, item: DocumentItem) -> list[Chunk]:
        text = item.get_text_content()
        return [
            Chunk(
                id=f"{item.id}:0",
                item_id=item.id,
                chunk_index=0,
                chunk_text=text,
                content_type="text",
                citation=CitationInfo(
                    spans=(CitationSpan(element_id=f"{item.id}-text"),)
                ),
            )
        ]


SCOPE = ConnectorScope(scope_type="folder", scope_value="root", display_name="Root")
@pytest.mark.asyncio
async def test_pipeline_batches_payloads_bounds_fetches_and_advances_checkpoint() -> None:
    connector = StubConnector()
    sink = RecordingSink()
    pipeline = ConnectorPipeline(
        connector,
        sink,
        tenant_id="tenant-1",
        connector_id="connector-1",
        config=ConnectorPipelineConfig(
            fetch_concurrency=2,
        ),
        chunker=StubChunker(),  # type: ignore[arg-type]
    )

    result = await pipeline.run_scope(SCOPE, SourceCheckpoint())

    assert result.discovered_changes == 3
    assert result.processed_items == 2
    assert result.written_chunks == 2
    assert result.deleted_items == 1
    assert result.replaced_items == 2
    assert result.checkpoint_advanced is True
    assert result.checkpoint == SourceCheckpoint(cursor="complete")
    assert connector.max_active_fetches == 2
    assert [item.id for item in sink.items] == ["root"]
    assert [len(chunks) for _, chunks in sink.writes] == [1, 1]
    assert sink.deletes == [
        ("tenant-1", "connector-1", "doc-old"),
    ]
    assert result.hierarchy[0].id == "root"
    assert [item.id for item, _ in sink.writes] == ["doc-2", "doc-1"]
    assert [chunks[0].chunk_text for _, chunks in sink.writes] == [
        "doc-2 " + "x" * 150,
        "doc-1 " + "x" * 150,
    ]


@pytest.mark.asyncio
async def test_pipeline_does_not_advance_checkpoint_after_partial_failure() -> None:
    initial = SourceCheckpoint(cursor="before")
    connector = StubConnector(fail_document="doc-2")
    sink = RecordingSink()
    pipeline = ConnectorPipeline(
        connector,
        sink,
        tenant_id="tenant-1",
        connector_id="connector-1",
        config=ConnectorPipelineConfig(
            continue_on_error=True,
            fetch_hierarchy=False,
        ),
        chunker=StubChunker(),  # type: ignore[arg-type]
    )

    result = await pipeline.run_scope(SCOPE, initial)

    assert result.checkpoint_advanced is False
    assert result.checkpoint == initial
    assert result.processed_items == 1
    assert result.failures[0].item_id == "doc-2"
    assert result.failures[0].operation == "fetch"
