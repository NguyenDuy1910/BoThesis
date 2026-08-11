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
    HierarchyNode,
    SourceChange,
    SourceChangeType,
    SourceDocument,
)
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

    async def delete_document(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        document_id: str,
    ) -> None:
        """Soft-delete all points for one tenant-owned document."""


@dataclass(frozen=True, slots=True)
class PipelineFailure:
    external_id: str
    operation: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class PipelineResult:
    checkpoint: ConnectorCheckpoint
    checkpoint_advanced: bool
    discovered_changes: int
    processed_documents: int
    written_chunks: int
    deleted_documents: int
    replaced_documents: int
    hierarchy: tuple[HierarchyNode, ...] = ()
    failures: tuple[PipelineFailure, ...] = ()
    duration_ms: int = 0


class ConnectorPipelineError(RuntimeError):
    def __init__(self, result: PipelineResult) -> None:
        self.result = result
        super().__init__(f"Connector pipeline failed for {len(result.failures)} document(s)")


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
        deleted_documents = 0
        replaced_documents = 0
        processed_documents = 0
        written_chunks = 0
        payload_buffer: deque[QdrantChunkRecord] = deque()

        for change in changes:
            if change.change_type != SourceChangeType.DELETE:
                continue
            try:
                await self._sink.delete_document(
                    tenant_id=self._context.tenant_id,
                    connector_id=self._context.connector_id,
                    document_id=change.external_id,
                )
                deleted_documents += 1
            except Exception as exc:
                failures.append(_failure(change.external_id, "delete", exc))

        upserts = [
            change for change in changes if change.change_type == SourceChangeType.UPSERT
        ]
        for start in range(0, len(upserts), self._config.fetch_concurrency):
            change_batch = upserts[start : start + self._config.fetch_concurrency]
            loaded = await asyncio.gather(
                *(self._load_document(change) for change in change_batch),
                return_exceptions=True,
            )
            for change, outcome in zip(change_batch, loaded, strict=True):
                if isinstance(outcome, BaseException):
                    failures.append(_failure(change.external_id, "fetch", outcome))
                    continue
                try:
                    records = build_qdrant_records(
                        outcome,
                        self._context,
                        chunking=self._config.chunking,
                    )
                    # Replace semantics remove stale trailing chunks when a
                    # newer document version produces fewer chunks.
                    await self._sink.delete_document(
                        tenant_id=self._context.tenant_id,
                        connector_id=self._context.connector_id,
                        document_id=outcome.external_id,
                    )
                    replaced_documents += 1
                    processed_documents += 1
                    payload_buffer.extend(records)
                    while len(payload_buffer) >= self._config.payload_batch_size:
                        write_batch = [
                            payload_buffer.popleft()
                            for _ in range(self._config.payload_batch_size)
                        ]
                        written_chunks += await self._write_batch(write_batch)
                except Exception as exc:
                    failures.append(_failure(change.external_id, "process", exc))

        if payload_buffer:
            try:
                written_chunks += await self._write_batch(list(payload_buffer))
            except Exception as exc:
                failures.append(_failure("<batch>", "write", exc))

        hierarchy: tuple[HierarchyNode, ...] = ()
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
            processed_documents=processed_documents,
            written_chunks=written_chunks,
            deleted_documents=deleted_documents,
            replaced_documents=replaced_documents,
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
            result.processed_documents,
            result.written_chunks,
            result.deleted_documents,
            result.replaced_documents,
            len(result.failures),
            result.duration_ms,
        )
        if failures and not self._config.continue_on_error:
            raise ConnectorPipelineError(result)
        return result

    async def _load_document(self, change: SourceChange) -> SourceDocument:
        document, acl = await asyncio.gather(
            self._connector.fetch_document(change.external_id),
            self._connector.fetch_acl(change.external_id),
        )
        if document.external_id != change.external_id:
            raise ValueError(
                f"Connector returned document {document.external_id!r} for change {change.external_id!r}"
            )
        if document.source.value != self._connector.source:
            raise ValueError(
                f"Connector source {self._connector.source!r} returned {document.source.value!r}"
            )
        return document.model_copy(
            update={
                "acl": acl,
                "external_version": document.external_version or change.external_version,
                "etag": document.etag or change.etag,
                "doc_updated_at": document.doc_updated_at or change.last_modified_at,
            },
            deep=True,
        )

    async def _write_batch(self, records: Sequence[QdrantChunkRecord]) -> int:
        written = await self._sink.write(records)
        if written != len(records):
            raise RuntimeError(
                f"Payload sink acknowledged {written} of {len(records)} records"
            )
        return written


def _deduplicate_changes(changes: list[SourceChange]) -> list[SourceChange]:
    by_external_id: dict[str, SourceChange] = {}
    for change in changes:
        # Moving a duplicate to the end preserves the source's latest ordering.
        by_external_id.pop(change.external_id, None)
        by_external_id[change.external_id] = change
    return list(by_external_id.values())


def _failure(external_id: str, operation: str, exc: BaseException) -> PipelineFailure:
    message = str(exc).strip()
    if len(message) > 500:
        message = f"{message[:497]}..."
    return PipelineFailure(
        external_id=external_id,
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
