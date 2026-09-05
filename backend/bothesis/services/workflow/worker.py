"""Temporal worker bootstrap and explicit workflow/activity registration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from config import AppConfig, get_config

from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.db.engine import get_session_factory
from bothesis.document_index import ItemIndex, SemanticContextualizer
from bothesis.runtime import AppRuntime
from bothesis.services.workflow import TemporalSettings
from bothesis.services.workflow.client import TemporalClientProvider
from bothesis.services.workflow.ingestion_activity import IngestionActivity
from bothesis.services.workflow.ingestion_workflow import IngestionWorkflow


class TemporalWorker:
    """Register and run BoThesis application workflows and Activities."""

    def __init__(
        self,
        settings: TemporalSettings | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self._settings = settings or TemporalSettings.from_environment()
        self._config = config or get_config()
        self._runtime = AppRuntime(self._config)
        self._contextualization_transport: OpenRouterTransport | None = None
        self._index: ItemIndex | None = None

    async def run(self) -> None:
        client = await TemporalClientProvider(self._settings).get()
        worker_config = self._config.worker
        ingestion = self._configured_ingestion_activity()
        worker = Worker(
            client,
            task_queue=self._settings.task_queue,
            workflows=[IngestionWorkflow],
            activities=[ingestion.ingest_items],
            # Importing a submodule of ``bothesis.services`` executes that
            # package's database-backed public boundary. Pass through only the
            # already-loaded workflow module and its lightweight contracts;
            # the Workflow code itself remains sandboxed and deterministic.
            workflow_runner=SandboxedWorkflowRunner(
                restrictions=SandboxRestrictions.default.with_passthrough_modules(
                    "bothesis.services",
                    "bothesis.services.workflow.ingestion_workflow",
                    "bothesis.services.workflow",
                )
            ),
            max_concurrent_activities=worker_config.max_concurrent_activities,
            max_task_queue_activities_per_second=worker_config.activity_rate_limit,
            graceful_shutdown_timeout=timedelta(
                seconds=worker_config.graceful_shutdown_seconds
            ),
        )
        try:
            await worker.run()
        finally:
            await self._close()

    def _configured_ingestion_activity(self) -> IngestionActivity:
        """Build the ingestion Activity from configuration, not the environment."""

        model = self._config.model
        index = self._config.vector_index
        contextualizer = None
        if model.contextualization_enabled:
            self._contextualization_transport = OpenRouterTransport(
                base_url=model.openrouter_base_url,
                model=model.contextualization_model,
            )
            contextualizer = SemanticContextualizer(
                self._contextualization_transport,
                model_name=model.contextualization_model,
            )
        # Indexing runs longer than a request, so it uses its own client timeout.
        self._index = ItemIndex(
            collection_name=index.collection,
            url=index.url,
            api_key=index.api_key,
            prefer_grpc=index.prefer_grpc,
            timeout=self._config.worker.indexing_timeout_seconds,
            embedder=OpenRouterTransport(base_url=model.openrouter_base_url),
            semantic_contextualizer=contextualizer,
            embedding_batch_size=index.embedding_batch_size,
        )
        return IngestionActivity(
            get_session_factory(),
            self._index,
            self._runtime.object_storage(),
            credential_encryption_key=(
                self._config.integration.credential_encryption_key
            ),
            preview=self._runtime.knowledge_preview(),
        )

    async def _close(self) -> None:
        if self._contextualization_transport is not None:
            await self._contextualization_transport.aclose()
        if self._index is not None:
            await self._index.aclose()
        await self._runtime.aclose()


async def _main() -> None:
    load_dotenv(Path(__file__).parents[2] / ".env", override=False)
    await TemporalWorker().run()


if __name__ == "__main__":
    asyncio.run(_main())


__all__ = ["TemporalWorker"]
