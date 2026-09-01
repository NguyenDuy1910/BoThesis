"""The complete durable application workflow for connector ingestion."""

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
from bothesis.db.models import Item, ExternalResource, IngestionSource
from bothesis.services import (
    AdminNotFoundError,
    AdminValidationError,
    InvalidDocumentStateError,
    IntegrationService,
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
    from bothesis.document_index import ChunkContextGenerator, EmbeddingService
    from bothesis.document_index.raw_storage import DocumentStorage
    from bothesis.document_index.vector_store import VectorStore
    from bothesis.connector.registry import ConnectorRegistry
    from bothesis.services.preview import KnowledgePreviewService

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
        registry: ConnectorRegistry | None = None,
        credential_encryption_key: str | None = None,
        pipeline_config: ConnectorPipelineConfig | None = None,
        embedding_batch_size: int = 32,
        semantic_contextualizer: ChunkContextGenerator | None = None,
        preview_service: KnowledgePreviewService | None = None,
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
        self._preview_service = preview_service

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
                UUID(input.source_id),
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
            source_id=input.source_id,
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
        source_id: UUID,
        *,
        test_connection: bool,
    ) -> PipelineResult:
        """Resolve the connector, detect changes, index them, and checkpoint."""

        from bothesis.connector import ConnectorPipeline, ConnectorPipelineConfig
        from bothesis.connector.file.file_connector import FileConnector
        from bothesis.document_index.knowledge_sink import QdrantKnowledgeSink
        from bothesis.services.preview import KnowledgePreviewService

        session_factory, store, embedder, raw_storage = self._dependencies()
        async with session_factory() as session:
            source, connector = await IntegrationService(
                session,
                registry=self._registry,
                credential_encryption_key=self._credential_encryption_key,
            ).runtime_for_source(source_id)
            resolved_source_id = source.id
            integration_connection_id = source.integration_connection_id
            connector_key = source.integration_connection.connector_key
            tenant_id = source.integration_connection.tenant_id
            checkpoint_data = dict(source.checkpoint or {})

        if connector.source != connector_key:
            raise ValueError("connector key does not match integration connection")
        set_storage = getattr(connector, "set_storage", None)
        if set_storage is not None:
            set_storage(raw_storage)
        if isinstance(connector, FileConnector):
            await self._load_file_records(connector, resolved_source_id)

        scopes = await connector.list_scopes()
        if len(scopes) != 1:
            raise ValueError("an ingestion source must resolve to exactly one runtime scope")
        checkpoint = connector.checkpoint_model.model_validate(checkpoint_data)
        sink = QdrantKnowledgeSink(
            store,
            embedder,
            session_factory=session_factory,
            ingestion_source_id=resolved_source_id,
            embedding_batch_size=self._embedding_batch_size,
            semantic_contextualizer=self._semantic_contextualizer,
            preview_service=(
                self._preview_service or KnowledgePreviewService(raw_storage)
            ),
        )
        pipeline = ConnectorPipeline(
            connector,
            sink,
            tenant_id=str(tenant_id),
            connector_id=str(integration_connection_id),
            config=self._pipeline_config or ConnectorPipelineConfig(),
        )
        result = await pipeline.run_scope(
            scopes[0],
            checkpoint,
            test_connection=test_connection,
        )
        await self._complete(resolved_source_id, result)
        return result

    async def _load_file_records(
        self,
        connector: FileConnector,
        source_id: UUID,
    ) -> None:
        session_factory, _, _, _ = self._dependencies()
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(Item, ExternalResource)
                    .join(ExternalResource, ExternalResource.item_id == Item.id)
                    .where(
                        ExternalResource.ingestion_source_id == source_id,
                        ExternalResource.deleted_at.is_(None),
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
                    "external_id": external_resource.external_id,
                    "file_name": item.metadata_.get("file_name") or item.title,
                    "storage_key": item.storage_key,
                    "size_bytes": item.size_bytes,
                    "mime_type": item.mime_type,
                    "provider_version": external_resource.external_version,
                    "uploaded_at": (
                        item.metadata_.get("uploaded_at")
                        or item.created_at.isoformat()
                    ),
                    "modified_at": (
                        external_resource.external_updated_at or item.created_at
                    ).isoformat(),
                    "metadata": dict(item.metadata_),
                    "acl": {},
                }
                for item, external_resource in rows
            ]
        )

    async def _complete(self, source_id: UUID, result: PipelineResult) -> None:
        session_factory, _, _, _ = self._dependencies()
        async with session_factory.begin() as session:
            source = await session.scalar(
                select(IngestionSource)
                .where(IngestionSource.id == source_id)
                .with_for_update()
            )
            if source is None or source.deleted_at is not None:
                raise InvalidDocumentStateError(f"ingestion source not found: {source_id}")
            if result.checkpoint_advanced:
                source.checkpoint = result.checkpoint.model_dump(mode="json")
            finished = datetime.now(UTC)
            source.last_ingested_at = finished
            source.last_indexed_at = finished
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
