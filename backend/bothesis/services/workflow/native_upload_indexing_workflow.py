"""Durable background indexing for one already-stored native upload."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from bothesis.services.workflow import (
    NATIVE_UPLOAD_INDEXING_ACTIVITY_NAME,
    NATIVE_UPLOAD_INDEXING_WORKFLOW_NAME,
    NativeUploadIndexingInput,
    NativeUploadIndexingResult,
)


@workflow.defn(name=NATIVE_UPLOAD_INDEXING_WORKFLOW_NAME)
class NativeUploadIndexingWorkflow:
    """Run the existing Item indexing pipeline outside the upload request."""

    @workflow.run
    async def run(
        self, input: NativeUploadIndexingInput
    ) -> NativeUploadIndexingResult:
        return await workflow.execute_activity(
            NATIVE_UPLOAD_INDEXING_ACTIVITY_NAME,
            input,
            result_type=NativeUploadIndexingResult,
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(minutes=2),
                maximum_attempts=5,
            ),
        )


__all__ = ["NativeUploadIndexingWorkflow"]
