"""The complete durable application workflow for plugin ingestion."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
from sqlalchemy import select
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from bothesis.connector.pipeline import ConnectorPipelineError, PipelineResult
from bothesis.db.models import Item, ItemOrigin, PluginBinding
from bothesis.services import (
    AdminNotFoundError,
    AdminValidationError,
    InvalidDocumentStateError,
    PluginService,
)
from bothesis.workflow import (
    INGESTION_ACTIVITY_NAME,
    INGESTION_WORKFLOW_NAME,
    IngestionProgress,
    IngestionResult,
    IngestionWorkflowInput,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from bothesis.connector import ConnectorPipelineConfig
    from bothesis.connector.file.file_connector import FileConnector
    from bothesis.document_index import EmbeddingService
    from bothesis.document_index.raw_storage import DocumentStorage
    from bothesis.document_index.semantic_contextualizer import SemanticContextualizer
    from bothesis.document_index.vector_store import VectorStore
    from bothesis.plugin.registry import PluginRegistry

_NON_RETRYABLE_FAILURE_TYPES = frozenset(
    {
        "AdminNotFoundError",
        "InvalidDocumentStateError",
        "PermissionError",
        "ValueError",
    }
)


@workflow.defn(name=INGESTION_WORKFLOW_NAME)
class IngestionWorkflow:
    """Discover, process, index, delete, and checkpoint connector changes."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        store: VectorStore | None = None,
        embedder: EmbeddingService | None = None,
        raw_storage: DocumentStorage | None = None,
        *,
        registry: PluginRegistry | None = None,
        credential_encryption_key: str | None = None,
        pipeline_config: ConnectorPipelineConfig | None = None,
        embedding_batch_size: int = 32,
        semantic_contextualizer: SemanticContextualizer | None = None,
    ) -> None:
        # Temporal constructs a dependency-free instance for deterministic
        # orchestration. The worker constructs a configured instance and
        # registers its Activity method for side-effecting ingestion.
        self._progress = IngestionProgress()
        self._session_factory = session_factory
        self._store = store
        self._embedder = embedder
        self._raw_storage = raw_storage
        self._registry = registry
        self._credential_encryption_key = credential_encryption_key
        self._pipeline_config = pipeline_config
        self._embedding_batch_size = embedding_batch_size
        self._semantic_contextualizer = semantic_contextualizer

    @workflow.run
    async def run(self, input: IngestionWorkflowInput) -> IngestionResult:
        """Durably execute the retryable connector ingestion Activity."""

        self._progress = IngestionProgress(phase="running")
        try:
            result = await workflow.execute_activity(
                INGESTION_ACTIVITY_NAME,
                input,
                result_type=IngestionResult,
                start_to_close_timeout=timedelta(hours=8),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=2),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(minutes=2),
                    maximum_attempts=5,
                ),
            )
        except Exception:
            self._progress = IngestionProgress(phase="failed")
            raise
        self._progress = IngestionProgress(
            phase="completed",
            discovered_count=result.discovered_count,
            processed_count=result.processed_count,
            indexed_count=result.indexed_count,
            deleted_count=result.deleted_count,
            failed_count=result.failed_count,
        )
        return result

    @workflow.query
    def progress(self) -> IngestionProgress:
        return self._progress

    @activity.defn(name=INGESTION_ACTIVITY_NAME)
    async def run_ingestion(self, input: IngestionWorkflowInput) -> IngestionResult:
        """Run the complete side-effecting connector-to-index pipeline."""

        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            result = await self._ingest(
                UUID(input.binding_id),
                test_connection=input.test_connection,
            )
        except ConnectorPipelineError as exc:
            non_retryable = bool(exc.result.failures) and all(
                self._is_non_retryable_failure(
                    failure.error_type,
                    failure.message,
                )
                for failure in exc.result.failures
            )
            raise ApplicationError(
                str(exc),
                [asdict(failure) for failure in exc.result.failures],
                type=(
                    "IngestionItemError"
                    if non_retryable
                    else "IngestionTransientError"
                ),
                non_retryable=non_retryable,
            ) from exc
        except httpx.HTTPStatusError as exc:
            non_retryable = exc.response.status_code in {400, 401, 403, 404, 422}
            raise ApplicationError(
                str(exc),
                type="ConnectorHTTPError",
                non_retryable=non_retryable,
            ) from exc
        except (
            AdminNotFoundError,
            AdminValidationError,
            InvalidDocumentStateError,
            PermissionError,
            ValueError,
        ) as exc:
            raise ApplicationError(
                str(exc),
                type=type(exc).__name__,
                non_retryable=True,
            ) from exc
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

        activity.heartbeat(
            {
                "phase": "completed",
                "processed_count": result.processed_items,
                "indexed_count": result.written_chunks,
            }
        )
        return IngestionResult(
            binding_id=input.binding_id,
            discovered_count=result.discovered_changes,
            processed_count=result.processed_items,
            indexed_count=result.written_chunks,
            deleted_count=result.deleted_items,
            failed_count=len(result.failures),
            checkpoint_advanced=result.checkpoint_advanced,
            duration_ms=result.duration_ms,
        )

    async def _ingest(
        self,
        binding_id: UUID,
        *,
        test_connection: bool,
    ) -> PipelineResult:
        """Resolve the connector, detect changes, index them, and checkpoint."""

        from bothesis.connector import ConnectorPipeline, ConnectorPipelineConfig
        from bothesis.connector.file.file_connector import FileConnector
        from bothesis.document_index.knowledge_sink import QdrantKnowledgeSink

        session_factory, store, embedder, raw_storage = self._dependencies()
        async with session_factory() as session:
            binding, connector = await PluginService(
                session,
                registry=self._registry,
                credential_encryption_key=self._credential_encryption_key,
            ).runtime_for_binding(binding_id)
            resolved_binding_id = binding.id
            connector_id = binding.connection_id
            plugin_key = binding.connection.plugin_key
            tenant_id = binding.connection.tenant_id
            checkpoint_data = dict(binding.checkpoint or {})

        if connector.source != plugin_key:
            raise ValueError("Plugin key does not match Connection")
        set_storage = getattr(connector, "set_storage", None)
        if set_storage is not None:
            set_storage(raw_storage)
        if isinstance(connector, FileConnector):
            await self._load_file_records(connector, resolved_binding_id)

        scopes = await connector.list_scopes()
        if len(scopes) != 1:
            raise ValueError(
                "a Plugin Binding must resolve to exactly one runtime scope"
            )
        checkpoint = connector.checkpoint_model.model_validate(checkpoint_data)
        sink = QdrantKnowledgeSink(
            store,
            embedder,
            session_factory=session_factory,
            binding_id=resolved_binding_id,
            embedding_batch_size=self._embedding_batch_size,
            semantic_contextualizer=self._semantic_contextualizer,
        )
        pipeline = ConnectorPipeline(
            connector,
            sink,
            tenant_id=str(tenant_id),
            connector_id=str(connector_id),
            config=self._pipeline_config or ConnectorPipelineConfig(),
        )
        result = await pipeline.run_scope(
            scopes[0],
            checkpoint,
            test_connection=test_connection,
        )
        await self._complete(resolved_binding_id, result)
        return result

    async def _load_file_records(
        self,
        connector: FileConnector,
        binding_id: UUID,
    ) -> None:
        session_factory, _, _, _ = self._dependencies()
        async with session_factory() as session:
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
        connector.set_records(
            [
                {
                    "external_id": origin.external_id,
                    "file_name": item.metadata_.get("file_name") or item.title,
                    "storage_key": item.storage_key,
                    "size_bytes": item.size_bytes,
                    "mime_type": item.mime_type,
                    "provider_version": origin.external_version,
                    "uploaded_at": (
                        item.metadata_.get("uploaded_at")
                        or item.created_at.isoformat()
                    ),
                    "modified_at": (
                        origin.external_updated_at or item.created_at
                    ).isoformat(),
                    "metadata": dict(item.metadata_),
                    "acl": {},
                }
                for item, origin in rows
            ]
        )

    async def _complete(self, binding_id: UUID, result: PipelineResult) -> None:
        session_factory, _, _, _ = self._dependencies()
        async with session_factory.begin() as session:
            binding = await session.scalar(
                select(PluginBinding)
                .where(PluginBinding.id == binding_id)
                .with_for_update()
            )
            if binding is None or binding.deleted_at is not None:
                raise InvalidDocumentStateError(
                    f"Plugin Binding not found: {binding_id}"
                )
            if result.checkpoint_advanced:
                binding.checkpoint = result.checkpoint.model_dump(mode="json")
            finished = datetime.now(UTC)
            binding.last_synced_at = finished
            binding.last_indexed_at = finished
            await session.flush()

    def _dependencies(
        self,
    ) -> tuple[
        async_sessionmaker[AsyncSession],
        VectorStore,
        EmbeddingService,
        DocumentStorage,
    ]:
        if (
            self._session_factory is None
            or self._store is None
            or self._embedder is None
            or self._raw_storage is None
        ):
            raise RuntimeError("ingestion Activity dependencies are not configured")
        return (
            self._session_factory,
            self._store,
            self._embedder,
            self._raw_storage,
        )

    @staticmethod
    async def _heartbeat() -> None:
        while True:
            activity.heartbeat({"phase": "running"})
            await asyncio.sleep(30)

    @staticmethod
    def _is_non_retryable_failure(error_type: str, message: str) -> bool:
        if error_type in _NON_RETRYABLE_FAILURE_TYPES:
            return True
        if error_type != "HTTPStatusError":
            return False
        return any(token in message for token in ("400", "401", "403", "404", "422"))


__all__ = ["IngestionWorkflow"]
