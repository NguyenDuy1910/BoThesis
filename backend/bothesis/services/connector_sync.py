"""Checkpoint-driven connector synchronization composition."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from bothesis.connector import ConnectorPipeline, ConnectorPipelineConfig
from bothesis.connector.pipeline import PipelineResult
from bothesis.connector.base import BaseSourceConnector
from bothesis.connector.file.file_connector import FileConnector
from bothesis.connector.protocol import ConnectorScope
from bothesis.db.models import ConnectorScope as StoredConnectorScope
from bothesis.db.models import Item, SyncRun
from bothesis.document_index.connector_sink import QdrantConnectorIndexSink
from bothesis.document_index.embedding import EmbeddingService
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer
from bothesis.document_index.vector_store import VectorStore
from bothesis.document_index.raw_storage import DocumentStorage
from bothesis.services import InvalidDocumentStateError


class ConnectorSyncService:
    """Run one retry-safe scope sync and advance its checkpoint on success."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: VectorStore,
        embedder: EmbeddingService,
        raw_storage: DocumentStorage,
        *,
        pipeline_config: ConnectorPipelineConfig | None = None,
        embedding_batch_size: int = 32,
        semantic_contextualizer: SemanticContextualizer | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._embedder = embedder
        self._raw_storage = raw_storage
        self._pipeline_config = pipeline_config or ConnectorPipelineConfig()
        self._embedding_batch_size = embedding_batch_size
        self._semantic_contextualizer = semantic_contextualizer

    async def run(
        self,
        run_id: UUID,
        connector: BaseSourceConnector,
        *,
        test_connection: bool = True,
    ) -> PipelineResult:
        run, stored_scope = await self._start_run(run_id, connector)
        set_storage = getattr(connector, "set_storage", None)
        if set_storage is not None:
            set_storage(self._raw_storage)
        if isinstance(connector, FileConnector):
            await self._load_file_records(connector, stored_scope.id)
        db_connector = stored_scope.connector
        tenant_id = str(db_connector.tenant_id)
        sink = QdrantConnectorIndexSink(
            self._store,
            self._embedder,
            embedding_batch_size=self._embedding_batch_size,
            semantic_contextualizer=self._semantic_contextualizer,
            session_factory=self._session_factory,
            connector_scope_id=stored_scope.id,
        )
        source_scope = ConnectorScope(
            scope_type=stored_scope.scope_type or "source",
            scope_value=stored_scope.scope_value,
            display_name=stored_scope.display_name or stored_scope.scope_value,
            metadata=dict(stored_scope.settings),
        )
        checkpoint = connector.checkpoint_model.model_validate(
            stored_scope.sync_checkpoint or {}
        )
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
            await self._complete_run(run.id, stored_scope.id, result)
        except Exception as exc:
            await self._fail_run(run.id, exc)
            raise
        return result

    async def _load_file_records(
        self, connector: FileConnector, scope_id: int
    ) -> None:
        async with self._session_factory() as session:
            items = list(
                await session.scalars(
                    select(Item).where(
                        Item.connector_scope_id == scope_id,
                        Item.item_type == "document",
                        Item.storage_key.is_not(None),
                        Item.status != "deleted",
                        Item.deleted_at.is_(None),
                    )
                )
            )
        connector.set_records(
            [
                {
                    "external_id": item.external_id,
                    "file_name": item.metadata_.get("file_name") or item.title,
                    "storage_key": item.storage_key,
                    "size_bytes": item.size_bytes,
                    "mime_type": item.mime_type,
                    "sha256": item.content_sha256,
                    "uploaded_at": item.metadata_.get("uploaded_at")
                    or item.created_at.isoformat(),
                    "modified_at": (
                        item.external_updated_at or item.created_at
                    ).isoformat(),
                    "metadata": dict(item.metadata_),
                    "acl": {
                        "source_reader_ids": item.allowed_principal_tokens,
                        "source_denied_reader_ids": item.denied_principal_tokens,
                    },
                }
                for item in items
            ]
        )

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
        result: PipelineResult,
    ) -> None:
        async with self._session_factory.begin() as session:
            run = await session.scalar(
                select(SyncRun).where(SyncRun.id == run_id).with_for_update()
            )
            if run is None or run.status != "running":
                raise InvalidDocumentStateError("sync run stopped before completion")
            run.discovered_item_count = result.discovered_changes
            run.processed_item_count = result.processed_items
            run.written_chunk_count = result.written_chunks
            run.deleted_item_count = result.deleted_items
            run.status = "completed"
            run.finished_at = datetime.now(UTC)
            scope = await session.get(StoredConnectorScope, scope_id)
            if scope is None:
                raise InvalidDocumentStateError(f"connector scope not found: {scope_id}")
            scope.sync_checkpoint = result.checkpoint.model_dump(mode="json")
            scope.last_synced_at = run.finished_at
            scope.last_indexed_at = run.finished_at
            await session.flush()

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
