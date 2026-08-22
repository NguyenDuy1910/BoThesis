"""Bounded connector-to-index processing orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

from .base import BaseSourceConnector
from .models import (
    ConnectorCheckpoint,
    ConnectorScope,
)
from bothesis.knowledge.protocol import AnyItem, ChangeType, ItemChange
from .qdrant import (
    ChunkingConfig,
    QdrantChunkRecord,
    QdrantPayloadContext,
    build_qdrant_records,
)

log = logging.getLogger(__name__)


class QdrantPayloadSink(Protocol):
    """Index boundary implemented by the embedding/Qdrant worker."""

    async def write(self, records: Sequence[QdrantChunkRecord]) -> int:
        """Embed and upsert every supplied record, returning the written count."""

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
    payload_batch_size: int = 64
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    continue_on_error: bool = False
    fetch_hierarchy: bool = True

    def __post_init__(self) -> None:
        if self.fetch_concurrency < 1:
            raise ValueError("fetch_concurrency must be at least one")
        if self.payload_batch_size < 1:
            raise ValueError("payload_batch_size must be at least one")


class ConnectorPipeline:
    """Process changes with bounded memory and stable, retry-safe point IDs.

    Failed runs never advance the returned checkpoint. A rerun can safely
    upsert the same deterministic records and retry only-completed source state.
    """

    def __init__(
        self,
        connector: BaseSourceConnector,
        sink: QdrantPayloadSink,
        *,
        context: QdrantPayloadContext,
        config: ConnectorPipelineConfig | None = None,
    ) -> None:
        self._connector = connector
        self._sink = sink
        self._context = context
        self._config = config or ConnectorPipelineConfig()

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
        deleted_items = 0
        replaced_items = 0
        processed_items = 0
        written_chunks = 0
        payload_buffer: deque[QdrantChunkRecord] = deque()

        for change in changes:
            if change.type != ChangeType.DELETE:
                continue
            try:
                await self._sink.soft_delete_item(
                    tenant_id=self._context.tenant_id,
                    connector_id=self._context.connector_id,
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
                    records = build_qdrant_records(
                        outcome,
                        self._context,
                        chunking=self._config.chunking,
                    )
                    # Replace semantics remove stale trailing chunks when a
                    # newer document version produces fewer chunks.
                    await self._sink.soft_delete_item(
                        tenant_id=self._context.tenant_id,
                        connector_id=self._context.connector_id,
                        item_id=outcome.id,
                    )
                    replaced_items += 1
                    processed_items += 1
                    payload_buffer.extend(records)
                    while len(payload_buffer) >= self._config.payload_batch_size:
                        write_batch = [
                            payload_buffer.popleft()
                            for _ in range(self._config.payload_batch_size)
                        ]
                        written_chunks += await self._write_batch(write_batch)
                except Exception as exc:
                    failures.append(_failure(change.item_id, "process", exc))

        if payload_buffer:
            try:
                written_chunks += await self._write_batch(list(payload_buffer))
            except Exception as exc:
                failures.append(_failure("<batch>", "write", exc))

        hierarchy: tuple[AnyItem, ...] = ()
        if self._config.fetch_hierarchy:
            try:
                hierarchy = tuple(await self._connector.fetch_hierarchy(scope))
            except Exception as exc:
                failures.append(_failure("<scope>", "hierarchy", exc))

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

    async def _load_item(self, change: ItemChange) -> AnyItem:
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
        return item

    async def _write_batch(self, records: Sequence[QdrantChunkRecord]) -> int:
        written = await self._sink.write(records)
        if written != len(records):
            raise RuntimeError(
                f"Payload sink acknowledged {written} of {len(records)} records"
            )
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
    "QdrantPayloadSink",
]
