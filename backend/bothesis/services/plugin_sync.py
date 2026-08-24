"""Checkpoint-driven execution of one Plugin Binding Sync Run."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from bothesis.connector import ConnectorPipeline, ConnectorPipelineConfig
from bothesis.connector.base import BaseSourceConnector
from bothesis.connector.file.file_connector import FileConnector
from bothesis.connector.pipeline import PipelineResult
from bothesis.db.models import Item, ItemOrigin, PluginBinding, SyncRun
from bothesis.document_index.embedding import EmbeddingService
from bothesis.document_index.knowledge_sink import QdrantKnowledgeSink
from bothesis.document_index.raw_storage import DocumentStorage
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer
from bothesis.document_index.vector_store import VectorStore
from bothesis.plugin.registry import PluginRegistry
from bothesis.services import InvalidDocumentStateError, PluginService


class PluginSyncService:
    """Resolve Binding -> Connection -> Plugin and advance only its checkpoint."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: VectorStore,
        embedder: EmbeddingService,
        raw_storage: DocumentStorage,
        *,
        registry: PluginRegistry | None = None,
        credential_encryption_key: str | None = None,
        pipeline_config: ConnectorPipelineConfig | None = None,
        embedding_batch_size: int = 32,
        semantic_contextualizer: SemanticContextualizer | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._embedder = embedder
        self._raw_storage = raw_storage
        self._registry = registry
        self._credential_encryption_key = credential_encryption_key
        self._pipeline_config = pipeline_config or ConnectorPipelineConfig()
        self._embedding_batch_size = embedding_batch_size
        self._semantic_contextualizer = semantic_contextualizer

    async def run(
        self,
        run_id: UUID,
        plugin: BaseSourceConnector | None = None,
        *,
        test_connection: bool = True,
    ) -> PipelineResult:
        run, binding = await self._start_run(run_id)
        runtime = plugin or await self._runtime(binding.id)
        if runtime.source != binding.connection.plugin_key:
            await self._fail_run(run.id, ValueError("Plugin key does not match Connection"))
            raise ValueError("Plugin key does not match Connection")
        set_storage = getattr(runtime, "set_storage", None)
        if set_storage is not None:
            set_storage(self._raw_storage)
        if isinstance(runtime, FileConnector):
            await self._load_file_records(runtime, binding.id)
        scopes = await runtime.list_scopes()
        if len(scopes) != 1:
            error = ValueError("a Plugin Binding must resolve to exactly one runtime scope")
            await self._fail_run(run.id, error)
            raise error
        checkpoint = runtime.checkpoint_model.model_validate(binding.checkpoint or {})
        sink = QdrantKnowledgeSink(
            self._store,
            self._embedder,
            session_factory=self._session_factory,
            binding_id=binding.id,
            embedding_batch_size=self._embedding_batch_size,
            semantic_contextualizer=self._semantic_contextualizer,
        )
        pipeline = ConnectorPipeline(
            runtime,
            sink,
            tenant_id=str(binding.connection.tenant_id),
            connector_id=str(binding.connection_id),
            config=self._pipeline_config,
        )
        try:
            result = await pipeline.run_scope(
                scopes[0], checkpoint, test_connection=test_connection
            )
            await self._complete_run(run.id, binding.id, result)
        except Exception as exc:
            await self._fail_run(run.id, exc)
            raise
        return result

    async def _runtime(self, binding_id: UUID) -> BaseSourceConnector:
        async with self._session_factory() as session:
            _, runtime = await PluginService(
                session,
                registry=self._registry,
                credential_encryption_key=self._credential_encryption_key,
            ).runtime_for_binding(binding_id)
            return runtime

    async def _load_file_records(
        self, plugin: FileConnector, binding_id: UUID
    ) -> None:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Item, ItemOrigin)
                    .join(ItemOrigin, ItemOrigin.item_id == Item.id)
                    .where(
                        ItemOrigin.binding_id == binding_id,
                        ItemOrigin.deleted_at.is_(None),
                        Item.item_type == "document",
                        Item.storage_key.is_not(None),
                        Item.status != "deleted",
                        Item.deleted_at.is_(None),
                    )
                )
            ).all()
        plugin.set_records(
            [
                {
                    "external_id": origin.external_id,
                    "file_name": item.metadata_.get("file_name") or item.title,
                    "storage_key": item.storage_key,
                    "size_bytes": item.size_bytes,
                    "mime_type": item.mime_type,
                    "provider_version": origin.external_version,
                    "uploaded_at": item.metadata_.get("uploaded_at")
                    or item.created_at.isoformat(),
                    "modified_at": (
                        origin.external_updated_at or item.created_at
                    ).isoformat(),
                    "metadata": dict(item.metadata_),
                    "acl": {},
                }
                for item, origin in rows
            ]
        )

    async def _start_run(self, run_id: UUID) -> tuple[SyncRun, PluginBinding]:
        overlap = False
        async with self._session_factory.begin() as session:
            run = await session.scalar(
                select(SyncRun)
                .options(
                    joinedload(SyncRun.binding).joinedload(PluginBinding.connection),
                    joinedload(SyncRun.binding).joinedload(PluginBinding.target_item),
                )
                .where(SyncRun.id == run_id)
                .with_for_update(of=SyncRun)
            )
            if run is None:
                raise InvalidDocumentStateError(f"sync run not found: {run_id}")
            if run.status != "pending":
                raise InvalidDocumentStateError(f"sync run is not runnable: {run.status}")
            binding = run.binding
            if (
                binding.status != "active"
                or binding.deleted_at is not None
                or binding.connection.status != "active"
                or binding.connection.deleted_at is not None
            ):
                raise InvalidDocumentStateError("Plugin Binding is not active")
            active = await session.scalar(
                select(SyncRun.id).where(
                    SyncRun.binding_id == binding.id,
                    SyncRun.id != run.id,
                    SyncRun.status == "running",
                )
            )
            if active is not None:
                run.status = "skipped"
                run.error_code = "overlap_skipped"
                run.finished_at = datetime.now(UTC)
                overlap = True
            else:
                run.status = "running"
                run.started_at = datetime.now(UTC)
                run.error_code = None
                run.error_message = None
            await session.flush()
        if overlap:
            raise InvalidDocumentStateError("Binding already has a running Sync Run")
        return run, binding

    async def _complete_run(
        self, run_id: UUID, binding_id: UUID, result: PipelineResult
    ) -> None:
        async with self._session_factory.begin() as session:
            run = await session.scalar(
                select(SyncRun).where(SyncRun.id == run_id).with_for_update()
            )
            if run is None or run.status != "running":
                raise InvalidDocumentStateError("sync run stopped before completion")
            finished = datetime.now(UTC)
            run.discovered_item_count = result.discovered_changes
            run.processed_item_count = result.processed_items
            run.written_chunk_count = result.written_chunks
            run.deleted_item_count = result.deleted_items
            run.status = "completed"
            run.finished_at = finished
            binding = await session.get(PluginBinding, binding_id)
            if binding is None:
                raise InvalidDocumentStateError(f"Plugin Binding not found: {binding_id}")
            binding.checkpoint = result.checkpoint.model_dump(mode="json")
            binding.last_synced_at = finished
            binding.last_indexed_at = finished
            await session.flush()

    async def _fail_run(self, run_id: UUID, exc: Exception) -> None:
        async with self._session_factory.begin() as session:
            run = await session.get(SyncRun, run_id)
            if run is None or run.status in {"cancelled", "skipped"}:
                return
            run.status = "failed"
            run.error_code = type(exc).__name__[:128]
            message = str(exc).strip() or type(exc).__name__
            run.error_message = message[:2_000]
            run.finished_at = datetime.now(UTC)


__all__ = ["PluginSyncService"]
