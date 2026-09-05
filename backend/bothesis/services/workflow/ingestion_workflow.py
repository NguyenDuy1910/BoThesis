"""Deterministic Temporal workflow for connector Item ingestion."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from bothesis.services.workflow import (
    INGESTION_ACTIVITY_NAME,
    INGESTION_WORKFLOW_NAME,
    IngestionProgress,
    IngestionResult,
    IngestionWorkflowInput,
)


@workflow.defn(name=INGESTION_WORKFLOW_NAME)
class IngestionWorkflow:
    """Coordinate one durable ingestion activity and expose progress."""

    def __init__(self) -> None:
        self._progress = IngestionProgress()

    @workflow.run
    async def run(self, input: IngestionWorkflowInput) -> IngestionResult:
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


__all__ = ["IngestionWorkflow"]
