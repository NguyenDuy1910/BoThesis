"""Trusted connector-snapshot worker composition."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from bothesis.connector import ConnectorPipeline, ConnectorPipelineConfig
from bothesis.connector.pipeline import PipelineResult
from bothesis.connector.base import BaseSourceConnector
from bothesis.connector.protocol import ConnectorScope
from bothesis.db.models import ConnectorScope as StoredConnectorScope
from bothesis.db.models import SyncRun
from bothesis.document_index.connector_sink import QdrantConnectorIndexSink
from bothesis.document_index.embedding import EmbeddingService
from bothesis.document_index.vector_store import VectorStore
from bothesis.services import InvalidDocumentStateError
from bothesis.services.document import DocumentService

log = logging.getLogger(__name__)


class ConnectorSyncService:
    """Build and activate one complete connector-scope snapshot.

    Every run starts from the connector's empty checkpoint intentionally. A
    database generation is a complete snapshot, not an incremental delta; the
    returned checkpoint is retained for source diagnostics and future
    delta-aware orchestration.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: VectorStore,
        embedder: EmbeddingService,
        *,
        pipeline_config: ConnectorPipelineConfig | None = None,
        embedding_batch_size: int = 32,
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._embedder = embedder
        self._pipeline_config = pipeline_config or ConnectorPipelineConfig()
        self._embedding_batch_size = embedding_batch_size

    async def run(
        self,
        run_id: UUID,
        connector: BaseSourceConnector,
        *,
        test_connection: bool = True,
    ) -> PipelineResult:
        run, stored_scope = await self._start_run(run_id, connector)
        db_connector = stored_scope.connector
        tenant_id = str(db_connector.tenant_id)
        sink = QdrantConnectorIndexSink(
            self._store,
            self._embedder,
            embedding_batch_size=self._embedding_batch_size,
            session_factory=self._session_factory,
            connector_scope_id=stored_scope.id,
            generation=run.generation,
        )
        source_scope = ConnectorScope(
            scope_type=stored_scope.scope_type or "source",
            scope_value=stored_scope.scope_value,
            display_name=stored_scope.display_name or stored_scope.scope_value,
            metadata=dict(stored_scope.settings),
        )
        checkpoint = connector.checkpoint_model()
        pipeline = ConnectorPipeline(
            connector,
            sink,
            tenant_id=tenant_id,
            connector_id=db_connector.id,
            config=self._pipeline_config,
        )

        try:
            result = await pipeline.run_scope(
                source_scope,
                checkpoint,
                test_connection=test_connection,
            )
            await self._complete_run(run.id, stored_scope.id, run.generation, result)
        except Exception as exc:
            await self._fail_run(run.id, exc)
            try:
                await sink.abort_generation(
                    tenant_id=tenant_id,
                    connector_id=db_connector.id,
                )
            except Exception:
                log.exception("could not tombstone failed connector generation %s", run.id)
            raise
        # Canonical activation commits first. If the derived-index switch has
        # a transient failure it can be retried without rebuilding evidence;
        # Qdrant is never the source of truth.
        await sink.activate_generation(
            tenant_id=tenant_id,
            connector_id=db_connector.id,
        )
        return result

    async def _start_run(
        self,
        run_id: UUID,
        connector: BaseSourceConnector,
    ) -> tuple[SyncRun, StoredConnectorScope]:
        async with self._session_factory.begin() as session:
            run = await session.scalar(
                select(SyncRun)
                .options(
                    joinedload(SyncRun.connector_scope).joinedload(
                        StoredConnectorScope.connector
                    )
                )
                .where(SyncRun.id == run_id)
                .with_for_update(of=SyncRun)
            )
            if run is None:
                raise InvalidDocumentStateError(f"sync run not found: {run_id}")
            if run.status not in {"pending", "running"}:
                raise InvalidDocumentStateError(
                    f"sync run is not runnable: {run.status}"
                )
            scope = run.connector_scope
            if connector.source != scope.connector.provider:
                raise ValueError(
                    f"connector provider {connector.source!r} does not match "
                    f"configured provider {scope.connector.provider!r}"
                )
            run.status = "running"
            run.started_at = run.started_at or datetime.now(UTC)
            run.error_code = None
            run.error_message = None
            await session.flush()
            return run, scope

    async def _complete_run(
        self,
        run_id: UUID,
        scope_id: int,
        generation: int,
        result: PipelineResult,
    ) -> None:
        async with self._session_factory.begin() as session:
            run = await session.scalar(
                select(SyncRun).where(SyncRun.id == run_id).with_for_update()
            )
            if run is None or run.status != "running":
                raise InvalidDocumentStateError("sync run stopped before completion")
            run.discovered_document_count = result.discovered_changes
            run.indexed_document_count = result.processed_items
            run.deleted_document_count = result.deleted_items
            run.status = "completed"
            run.finished_at = datetime.now(UTC)
            scope = await session.get(StoredConnectorScope, scope_id)
            if scope is None:
                raise InvalidDocumentStateError(f"connector scope not found: {scope_id}")
            scope.sync_checkpoint = result.checkpoint.model_dump(mode="json")
            scope.last_synced_at = run.finished_at
            await session.flush()
            await DocumentService(session).activate_generation_from_worker(
                scope_id,
                generation,
            )

    async def _fail_run(self, run_id: UUID, exc: Exception) -> None:
        async with self._session_factory.begin() as session:
            run = await session.get(SyncRun, run_id)
            if run is None or run.status == "cancelled":
                return
            run.status = "failed"
            run.error_code = type(exc).__name__[:128]
            message = str(exc).strip() or type(exc).__name__
            run.error_message = message[:2_000]
            run.finished_at = datetime.now(UTC)


__all__ = ["ConnectorSyncService"]
