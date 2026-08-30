"""Temporal worker bootstrap and explicit workflow/activity registration."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.db.engine import get_session_factory
from bothesis.document_index.raw_storage import S3DocumentStorage
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer
from bothesis.document_index.vector_store import VectorStore
from bothesis.services.preview import KnowledgePreviewRenderer, KnowledgePreviewService
from bothesis.services.ingestion_workflow import IngestionWorkflow
from bothesis.workflow import TemporalSettings
from bothesis.workflow.client import TemporalClientProvider


class TemporalWorker:
    """Register and run BoThesis application workflows and Activities."""

    def __init__(self, settings: TemporalSettings | None = None) -> None:
        self._settings = settings or TemporalSettings.from_environment()
        self._embedder: OpenRouterTransport | None = None
        self._contextualization_transport: OpenRouterTransport | None = None
        self._store: VectorStore | None = None
        self._storage: S3DocumentStorage | None = None

    async def run(self) -> None:
        client = await TemporalClientProvider(self._settings).get()
        ingestion = self._configured_ingestion_workflow()
        worker = Worker(
            client,
            task_queue=self._settings.task_queue,
            workflows=[IngestionWorkflow],
            activities=[ingestion.run_ingestion],
            # Importing a submodule of ``bothesis.services`` executes that
            # package's database-backed public boundary. Pass through only the
            # already-loaded workflow module and its lightweight contracts;
            # the Workflow code itself remains sandboxed and deterministic.
            workflow_runner=SandboxedWorkflowRunner(
                restrictions=SandboxRestrictions.default.with_passthrough_modules(
                    "bothesis.services",
                    "bothesis.services.ingestion_workflow",
                    "bothesis.workflow",
                )
            ),
            max_concurrent_activities=int(
                os.getenv("BOTHESIS_TEMPORAL_MAX_CONCURRENT_ACTIVITIES", "4")
            ),
            max_task_queue_activities_per_second=_optional_float(
                os.getenv("BOTHESIS_TEMPORAL_ACTIVITY_RATE_LIMIT")
            ),
            graceful_shutdown_timeout=timedelta(seconds=30),
        )
        try:
            await worker.run()
        finally:
            await self._close()

    def _configured_ingestion_workflow(self) -> IngestionWorkflow:
        self._store = VectorStore(
            collection_name=os.getenv("QDRANT_COLLECTION"),
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            prefer_grpc=_environment_boolean("QDRANT_PREFER_GRPC"),
            timeout=60,
        )
        self._embedder = OpenRouterTransport(
            base_url=os.getenv(
                "OPEN_ROUTER_BASE_URL", OpenRouterTransport.DEFAULT_BASE_URL
            )
        )
        semantic_contextualizer = None
        if _environment_boolean("BOTHESIS_CONTEXTUALIZATION_ENABLED"):
            model = os.getenv("BOTHESIS_CONTEXTUALIZATION_MODEL") or None
            self._contextualization_transport = OpenRouterTransport(
                base_url=os.getenv(
                    "OPEN_ROUTER_BASE_URL", OpenRouterTransport.DEFAULT_BASE_URL
                ),
                model=model,
            )
            semantic_contextualizer = SemanticContextualizer(
                self._contextualization_transport,
                model_name=model,
            )
        self._storage = _object_storage()
        return IngestionWorkflow(
            get_session_factory(),
            self._store,
            self._embedder,
            self._storage,
            credential_encryption_key=(
                os.getenv("BOTHESIS_INTEGRATION_ENCRYPTION_KEY") or None
            ),
            embedding_batch_size=int(
                os.getenv("BOTHESIS_DOCUMENT_EMBEDDING_BATCH_SIZE", "32")
            ),
            semantic_contextualizer=semantic_contextualizer,
            preview_service=KnowledgePreviewService(
                self._storage,
                renderer=KnowledgePreviewRenderer(
                    max_pages=int(os.getenv("BOTHESIS_PREVIEW_MAX_PAGES", "50")),
                    max_dimension=int(
                        os.getenv("BOTHESIS_PREVIEW_MAX_DIMENSION", "1600")
                    ),
                    webp_quality=int(
                        os.getenv("BOTHESIS_PREVIEW_WEBP_QUALITY", "80")
                    ),
                ),
                max_source_bytes=int(
                    os.getenv("BOTHESIS_PREVIEW_MAX_SOURCE_BYTES", "104857600")
                ),
            ),
        )

    async def _close(self) -> None:
        if self._embedder is not None:
            await self._embedder.aclose()
        if self._contextualization_transport is not None:
            await self._contextualization_transport.aclose()
        if self._store is not None:
            await self._store.aclose()
        if self._storage is not None:
            await self._storage.aclose()


def _object_storage() -> S3DocumentStorage:
    provider = (os.getenv("BOTHESIS_OBJECT_STORAGE_PROVIDER") or "aws_s3").strip()
    if provider == "cloudflare_r2":
        return S3DocumentStorage.for_cloudflare_r2(
            bucket=(
                os.getenv("BOTHESIS_R2_BUCKET")
                or os.getenv("BOTHESIS_OBJECT_STORAGE_BUCKET")
                or ""
            ),
            account_id=os.getenv("BOTHESIS_R2_ACCOUNT_ID") or None,
            endpoint_url=os.getenv("BOTHESIS_R2_ENDPOINT_URL") or None,
            access_key_id=os.getenv("BOTHESIS_R2_ACCESS_KEY_ID") or None,
            secret_access_key=os.getenv("BOTHESIS_R2_SECRET_ACCESS_KEY") or None,
            timeout_seconds=float(os.getenv("BOTHESIS_R2_TIMEOUT_SECONDS", "20")),
            max_pool_connections=int(
                os.getenv("BOTHESIS_R2_MAX_POOL_CONNECTIONS", "20")
            ),
        )
    if provider != "aws_s3":
        raise RuntimeError(
            "BOTHESIS_OBJECT_STORAGE_PROVIDER must be aws_s3 or cloudflare_r2"
        )
    return S3DocumentStorage(
        bucket=(
            os.getenv("BOTHESIS_S3_BUCKET")
            or os.getenv("BOTHESIS_OBJECT_STORAGE_BUCKET")
            or ""
        ),
        region=(
            os.getenv("BOTHESIS_S3_REGION")
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or None
        ),
        endpoint_url=(
            os.getenv("BOTHESIS_S3_ENDPOINT_URL")
            or os.getenv("BOTHESIS_OBJECT_STORAGE_ENDPOINT")
            or None
        ),
        addressing_style=(
            os.getenv("BOTHESIS_S3_ADDRESSING_STYLE") or "auto"
        ).strip(),
        timeout_seconds=float(os.getenv("BOTHESIS_S3_TIMEOUT_SECONDS", "20")),
        max_pool_connections=int(
            os.getenv("BOTHESIS_S3_MAX_POOL_CONNECTIONS", "20")
        ),
    )


def _environment_boolean(name: str, *, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be a JSON boolean") from exc
    if not isinstance(value, bool):
        raise RuntimeError(f"{name} must be a JSON boolean")
    return value


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("Temporal Activity rate limit must be positive")
    return parsed


async def _main() -> None:
    load_dotenv(Path(__file__).parents[2] / ".env", override=False)
    await TemporalWorker().run()


if __name__ == "__main__":
    asyncio.run(_main())


__all__ = ["TemporalWorker"]
