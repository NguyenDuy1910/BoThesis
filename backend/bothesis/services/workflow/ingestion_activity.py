"""Side-effecting Temporal activity for connector Item ingestion."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from bothesis.connector import ConnectorPipeline, ConnectorPipelineConfig
from bothesis.connector.file.file_connector import FileConnector
from bothesis.connector.pipeline import ConnectorPipelineError, PipelineResult
from bothesis.connector.registry import ConnectorRegistry
from bothesis.db.models import ExternalResource, IngestionSource, Item
from bothesis.document_index import ItemIndex
from bothesis.storage import DocumentStorage
from bothesis.services.ingestion_sources import IngestionSourceService
from bothesis.services.item_ingestion import ItemIngestionService
from bothesis.services import (
    AdminNotFoundError,
    AdminValidationError,
    InvalidDocumentStateError,
)
from bothesis.services.preview import KnowledgePreview
from bothesis.services.workflow import (
    INGESTION_ACTIVITY_NAME,
    IngestionResult,
    IngestionWorkflowInput,
)

_NON_RETRYABLE_FAILURE_TYPES = frozenset(
    {"AdminNotFoundError", "InvalidDocumentStateError", "PermissionError", "ValueError"}
)


class IngestionActivity:
    """Load Item data by stable IDs and run side-effecting ingestion."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        index: ItemIndex,
        raw_storage: DocumentStorage,
        *,
        registry: ConnectorRegistry | None = None,
        credential_encryption_key: str | None = None,
        pipeline_config: ConnectorPipelineConfig | None = None,
        preview: KnowledgePreview | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._index = index
        self._raw_storage = raw_storage
        self._registry = registry
        self._credential_encryption_key = credential_encryption_key
        self._pipeline_config = pipeline_config
        self._preview = preview

    @activity.defn(name=INGESTION_ACTIVITY_NAME)
    async def ingest_items(self, input: IngestionWorkflowInput) -> IngestionResult:
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            result = await self._ingest(
                UUID(input.source_id),
                test_connection=input.test_connection,
            )
        except ConnectorPipelineError as exc:
            non_retryable = bool(exc.result.failures) and all(
                self._is_non_retryable_failure(failure.error_type, failure.message)
                for failure in exc.result.failures
            )
            raise ApplicationError(
                str(exc),
                [asdict(failure) for failure in exc.result.failures],
                type="IngestionItemError"
                if non_retryable
                else "IngestionTransientError",
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
                str(exc), type=type(exc).__name__, non_retryable=True
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
        self, source_id: UUID, *, test_connection: bool
    ) -> PipelineResult:
        async with self._session_factory() as session:
            source, connector = await IngestionSourceService(
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
            set_storage(self._raw_storage)
        if isinstance(connector, FileConnector):
            await self._load_file_records(connector, resolved_source_id)
        scopes = await connector.list_scopes()
        if len(scopes) != 1:
            raise ValueError(
                "an ingestion source must resolve to exactly one runtime scope"
            )

        ingestion = ItemIngestionService(
            self._session_factory,
            index=self._index,
            ingestion_source_id=resolved_source_id,
            preview=self._preview or KnowledgePreview(self._raw_storage),
        )
        pipeline = ConnectorPipeline(
            connector,
            ingestion,
            tenant_id=str(tenant_id),
            connector_id=str(integration_connection_id),
            config=self._pipeline_config or ConnectorPipelineConfig(),
        )
        result = await pipeline.run_scope(
            scopes[0],
            connector.checkpoint_model.model_validate(checkpoint_data),
            test_connection=test_connection,
        )
        await self._complete(resolved_source_id, result)
        return result

    async def _load_file_records(
        self,
        connector: FileConnector,
        source_id: UUID,
    ) -> None:
        async with self._session_factory() as session:
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
                    "external_id": resource.external_id,
                    "file_name": item.metadata_.get("file_name") or item.title,
                    "storage_key": item.storage_key,
                    "size_bytes": item.size_bytes,
                    "mime_type": item.mime_type,
                    "provider_version": resource.external_version,
                    "uploaded_at": (
                        item.metadata_.get("uploaded_at") or item.created_at.isoformat()
                    ),
                    "modified_at": (
                        resource.external_updated_at or item.created_at
                    ).isoformat(),
                    "metadata": dict(item.metadata_),
                    "acl": {},
                }
                for item, resource in rows
            ]
        )

    async def _complete(self, source_id: UUID, result: PipelineResult) -> None:
        async with self._session_factory.begin() as session:
            source = await session.scalar(
                select(IngestionSource)
                .where(IngestionSource.id == source_id)
                .with_for_update()
            )
            if source is None or source.deleted_at is not None:
                raise InvalidDocumentStateError(
                    f"ingestion source not found: {source_id}"
                )
            if result.checkpoint_advanced:
                source.checkpoint = result.checkpoint.model_dump(mode="json")
            finished = datetime.now(UTC)
            source.last_ingested_at = finished
            source.last_indexed_at = finished
            await session.flush()

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


__all__ = ["IngestionActivity"]
