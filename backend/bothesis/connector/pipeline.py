"""Bounded connector-to-index processing orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from .base import BaseSourceConnector
from bothesis.connector.processing import DoclingChunker
from bothesis.connector.protocol import (
    AnyItem,
    ChangeType,
    Chunk,
    ConnectorCheckpoint,
    ConnectorScope,
    DocumentItem,
    DocumentKind,
    ItemChange,
)

log = logging.getLogger(__name__)


class ConnectorIndexSink(Protocol):
    """Index boundary supplied by ``document_index``.

    Connector orchestration supplies the final canonical document and evidence
    chunks. Contextualization, embedding, and payload projection happen behind
    this boundary.
    """

    async def write_item(
        self,
        item: AnyItem,
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> object:
        """Persist one canonical Item that does not require indexing."""

    async def write(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> int:
        """Replace one canonical item and return the number of chunks written."""

    async def soft_delete_item(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        item_id: str,
    ) -> None:
        """Soft-delete all points for one tenant-owned item."""


@dataclass(frozen=True, slots=True)
class PipelineFailure:
    item_id: str
    operation: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class PipelineResult:
    checkpoint: ConnectorCheckpoint
    checkpoint_advanced: bool
    discovered_changes: int
    processed_items: int
    written_chunks: int
    deleted_items: int
    replaced_items: int
    hierarchy: tuple[AnyItem, ...] = ()
    failures: tuple[PipelineFailure, ...] = ()
    duration_ms: int = 0


class ConnectorPipelineError(RuntimeError):
    def __init__(self, result: PipelineResult) -> None:
        self.result = result
        super().__init__(f"Connector pipeline failed for {len(result.failures)} item(s)")


@dataclass(frozen=True, slots=True)
class ConnectorPipelineConfig:
    fetch_concurrency: int = 8
    continue_on_error: bool = False
    fetch_hierarchy: bool = True

    def __post_init__(self) -> None:
        if self.fetch_concurrency < 1:
            raise ValueError("fetch_concurrency must be at least one")


class ConnectorPipeline:
    """Process changes with bounded memory and stable, retry-safe point IDs.

    Failed runs never advance the returned checkpoint. A rerun can safely
    upsert the same deterministic records and retry only-completed source state.
    """

    def __init__(
        self,
        connector: BaseSourceConnector,
        sink: ConnectorIndexSink,
        *,
        tenant_id: str,
        connector_id: str | int,
        config: ConnectorPipelineConfig | None = None,
        chunker: DoclingChunker | None = None,
    ) -> None:
        self._connector = connector
        self._sink = sink
        self._tenant_id = tenant_id
        self._connector_id = connector_id
        self._config = config or ConnectorPipelineConfig()
        self._chunker = chunker or DoclingChunker()

    async def run_scope(
        self,
        scope: ConnectorScope,
        checkpoint: ConnectorCheckpoint,
        *,
        test_connection: bool = False,
    ) -> PipelineResult:
        started_at = perf_counter()
        if test_connection:
            connected = await self._connector.test_connection()
            if not connected:
                raise ConnectionError(f"Connector {self._connector.source!r} is unavailable")

        changes = _deduplicate_changes(
            await self._connector.discover_changes(checkpoint, scope)
        )
        failures: list[PipelineFailure] = []
        hierarchy: tuple[AnyItem, ...] = ()
        if self._config.fetch_hierarchy:
            try:
                hierarchy = tuple(await self._connector.fetch_hierarchy(scope))
                for item in sorted(
                    hierarchy,
                    key=lambda value: (value.hierarchy.depth, value.id),
                ):
                    await self._sink.write_item(
                        item,
                        tenant_id=self._tenant_id,
                        connector_id=self._connector_id,
                    )
            except Exception as exc:
                failures.append(_failure("<scope>", "hierarchy", exc))
        deleted_items = 0
        replaced_items = 0
        processed_items = 0
        written_chunks = 0
        for change in changes:
            if change.type != ChangeType.DELETE:
                continue
            try:
                await self._sink.soft_delete_item(
                    tenant_id=self._tenant_id,
                    connector_id=self._connector_id,
                    item_id=change.item_id,
                )
                deleted_items += 1
            except Exception as exc:
                failures.append(_failure(change.item_id, "delete", exc))

        upserts = [
            change for change in changes if change.type != ChangeType.DELETE
        ]
        for start in range(0, len(upserts), self._config.fetch_concurrency):
            change_batch = upserts[start : start + self._config.fetch_concurrency]
            loaded = await asyncio.gather(
                *(self._load_item(change) for change in change_batch),
                return_exceptions=True,
            )
            for change, outcome in zip(change_batch, loaded, strict=True):
                if isinstance(outcome, BaseException):
                    failures.append(_failure(change.item_id, "fetch", outcome))
                    continue
                try:
                    chunks = await self._chunks_for(outcome)
                    written_chunks += await self._write(outcome, chunks)
                    replaced_items += 1
                    processed_items += 1
                except Exception as exc:
                    failures.append(_failure(change.item_id, "process", exc))

        advanced = not failures
        result = PipelineResult(
            checkpoint=(self._connector.next_checkpoint() if advanced else checkpoint),
            checkpoint_advanced=advanced,
            discovered_changes=len(changes),
            processed_items=processed_items,
            written_chunks=written_chunks,
            deleted_items=deleted_items,
            replaced_items=replaced_items,
            hierarchy=hierarchy,
            failures=tuple(failures),
            duration_ms=round((perf_counter() - started_at) * 1000),
        )
        log.info(
            "connector_pipeline source=%s scope=%s changes=%d documents=%d chunks=%d "
            "deleted=%d replaced=%d failures=%d duration_ms=%d",
            self._connector.source,
            scope.scope_value,
            result.discovered_changes,
            result.processed_items,
            result.written_chunks,
            result.deleted_items,
            result.replaced_items,
            len(result.failures),
            result.duration_ms,
        )
        if failures and not self._config.continue_on_error:
            raise ConnectorPipelineError(result)
        return result

    async def _load_item(self, change: ItemChange) -> DocumentItem:
        item_id = change.item_id
        item = change.item
        if item is None:
            item = await self._connector.fetch_item(item_id)
        if item.id != item_id:
            raise ValueError(
                f"Connector returned item {item.id!r} for change {item_id!r}"
            )
        if item.source.provider.value != self._connector.source:
            raise ValueError(
                f"Connector source {self._connector.source!r} returned {item.source.provider.value!r}"
            )
        if not isinstance(item, DocumentItem):
            raise ValueError(
                f"Connector change {item_id!r} did not produce a DocumentItem"
            )
        return item

    async def _chunks_for(self, item: DocumentItem) -> tuple[Chunk, ...]:
        chunks = await self._connector.fetch_chunks(item)
        resolved = (
            tuple(chunks)
            if chunks is not None
            else tuple(self._chunker.chunk_item(item))
        )
        if not resolved:
            if item.document_kind == DocumentKind.IMAGE:
                return ()
            raise ValueError(f"Document item {item.id!r} has no chunks")
        seen_ids: set[str] = set()
        seen_indexes: set[int] = set()
        for chunk in resolved:
            if chunk.item_id != item.id:
                raise ValueError(
                    f"Chunk {chunk.id!r} belongs to {chunk.item_id!r}, not {item.id!r}"
                )
            if chunk.id in seen_ids or chunk.chunk_index in seen_indexes:
                raise ValueError(f"Document item {item.id!r} has duplicate chunks")
            seen_ids.add(chunk.id)
            seen_indexes.add(chunk.chunk_index)
        return resolved

    async def _write(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
    ) -> int:
        written = await self._sink.write(
            item,
            chunks,
            tenant_id=self._tenant_id,
            connector_id=self._connector_id,
        )
        if written < 0:
            raise RuntimeError("Index sink returned a negative write count")
        return written


def _deduplicate_changes(changes: list[ItemChange]) -> list[ItemChange]:
    by_item_id: dict[str, ItemChange] = {}
    for change in changes:
        # Moving a duplicate to the end preserves the source's latest ordering.
        by_item_id.pop(change.item_id, None)
        by_item_id[change.item_id] = change
    return list(by_item_id.values())


def _failure(item_id: str, operation: str, exc: BaseException) -> PipelineFailure:
    message = str(exc).strip()
    if len(message) > 500:
        message = f"{message[:497]}..."
    return PipelineFailure(
        item_id=item_id,
        operation=operation,
        error_type=type(exc).__name__,
        message=message or type(exc).__name__,
    )


__all__ = [
    "ConnectorPipeline",
    "ConnectorPipelineConfig",
    "ConnectorPipelineError",
    "PipelineFailure",
    "PipelineResult",
    "ConnectorIndexSink",
]
