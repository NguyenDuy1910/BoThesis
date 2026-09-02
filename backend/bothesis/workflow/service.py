"""Application-facing Temporal execution, visibility, and schedule operations."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleDescription,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
    WorkflowExecution,
    WorkflowExecutionDescription,
    WorkflowQueryFailedError,
    WorkflowQueryRejectedError,
)
from temporalio.common import (
    SearchAttributeKey,
    SearchAttributePair,
    TypedSearchAttributes,
    WorkflowIDConflictPolicy,
    WorkflowIDReusePolicy,
)
from temporalio.exceptions import (
    WorkflowAlreadyStartedError,
)
from temporalio.service import RPCError, RPCStatusCode

from bothesis.workflow import (
    INGESTION_WORKFLOW_NAME,
    IngestionProgress,
    IngestionResult,
    IngestionWorkflowInput,
    TemporalSettings,
    WorkflowExecutionNotFoundError,
    ingestion_schedule_id,
    ingestion_workflow_id,
)
from bothesis.workflow.client import TemporalClientProvider

_TENANT_ID = SearchAttributeKey.for_keyword("TenantId")
_INGESTION_SOURCE_ID = SearchAttributeKey.for_keyword("IngestionSourceId")
_INTEGRATION_CONNECTION_ID = SearchAttributeKey.for_keyword("IntegrationConnectionId")
_CONNECTOR_KEY = SearchAttributeKey.for_keyword("ConnectorKey")
_WORKFLOW_CATEGORY = SearchAttributeKey.for_keyword("WorkflowCategory")
_TRIGGER_TYPE = SearchAttributeKey.for_keyword("TriggerType")

_OVERLAP_POLICIES = {
    "skip": ScheduleOverlapPolicy.SKIP,
    "queue": ScheduleOverlapPolicy.BUFFER_ONE,
    "replace": ScheduleOverlapPolicy.CANCEL_OTHER,
}
_STATUS_QUERY_VALUES = {
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Canceled",
    "canceled": "Canceled",
    "terminated": "Terminated",
    "timed_out": "TimedOut",
}


class TemporalWorkflowService:
    """Use Temporal as the sole runtime for ingestion execution state."""

    def __init__(
        self,
        client_provider: TemporalClientProvider | None = None,
        settings: TemporalSettings | None = None,
    ) -> None:
        self._provider = client_provider or TemporalClientProvider(settings)
        self._settings = self._provider.settings

    async def start_ingestion(
        self, input: IngestionWorkflowInput
    ) -> dict[str, Any]:
        client = await self._provider.get()
        workflow_id = ingestion_workflow_id(input.source_id)
        try:
            handle = await client.start_workflow(
                INGESTION_WORKFLOW_NAME,
                input,
                result_type=IngestionResult,
                id=workflow_id,
                task_queue=self._settings.task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                search_attributes=self._search_attributes(input),
                static_summary=f"Ingest {input.connector_key} source {input.source_id}",
            )
            description = await handle.describe()
            payload = self._execution_payload(description)
            payload["started"] = True
            return payload
        except WorkflowAlreadyStartedError:
            description = await client.get_workflow_handle(workflow_id).describe()
            payload = self._execution_payload(description)
            payload["started"] = False
            payload["conflict"] = "source_ingestion_already_running"
            return payload

    async def list_ingestions(
        self,
        *,
        tenant_id: str,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        source_id: str | None = None,
        integration_connection_id: str | None = None,
    ) -> dict[str, Any]:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("invalid workflow page")
        query = self._visibility_query(
            tenant_id=tenant_id,
            status=status,
            source_id=source_id,
            integration_connection_id=integration_connection_id,
        )
        client = await self._provider.get()
        offset = (page - 1) * page_size
        executions = [
            execution
            async for execution in client.list_workflows(
                query,
                limit=offset + page_size,
                page_size=min(1000, offset + page_size),
            )
        ]
        count = await client.count_workflows(query)
        return {
            "items": [
                self._execution_payload(execution)
                for execution in executions[offset : offset + page_size]
            ],
            "total": count.count,
            "page": page,
            "page_size": page_size,
        }

    async def describe_ingestion(
        self, workflow_id: str, *, include_progress: bool = True
    ) -> dict[str, Any]:
        client = await self._provider.get()
        handle = client.get_workflow_handle(workflow_id)
        try:
            description = await handle.describe()
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                raise WorkflowExecutionNotFoundError(workflow_id) from exc
            raise
        payload = self._execution_payload(description)
        if include_progress:
            try:
                progress = await handle.query(
                    "progress", result_type=IngestionProgress
                )
                payload["progress"] = self._progress_payload(progress)
            except (WorkflowQueryFailedError, WorkflowQueryRejectedError):
                pass
        return payload

    async def latest_ingestion(
        self, *, tenant_id: str, source_id: str
    ) -> dict[str, Any] | None:
        result = await self.list_ingestions(
            tenant_id=tenant_id,
            source_id=source_id,
            page=1,
            page_size=1,
        )
        if not result["items"]:
            return None
        return await self.describe_ingestion(result["items"][0]["id"])

    async def cancel_ingestion(self, workflow_id: str) -> dict[str, Any]:
        client = await self._provider.get()
        handle = client.get_workflow_handle(workflow_id)
        try:
            await handle.cancel()
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                raise WorkflowExecutionNotFoundError(workflow_id) from exc
            raise
        return await self.describe_ingestion(workflow_id, include_progress=False)

    async def upsert_schedule(
        self,
        input: IngestionWorkflowInput,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        scheduled_input = replace(input, trigger_type="scheduled")
        schedule = self._schedule(scheduled_input, values)
        schedule_id = ingestion_schedule_id(input.source_id)
        client = await self._provider.get()
        try:
            handle = await client.create_schedule(
                schedule_id,
                schedule,
                search_attributes=self._search_attributes(scheduled_input),
            )
        except ScheduleAlreadyRunningError:
            handle = client.get_schedule_handle(schedule_id)

            async def update(_: Any) -> ScheduleUpdate:
                return ScheduleUpdate(
                    schedule=schedule,
                    search_attributes=self._search_attributes(scheduled_input),
                )

            await handle.update(update)
        return self._schedule_payload(await handle.describe())

    async def describe_schedule(self, source_id: str) -> dict[str, Any] | None:
        client = await self._provider.get()
        handle = client.get_schedule_handle(ingestion_schedule_id(source_id))
        try:
            return self._schedule_payload(await handle.describe())
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                return None
            raise

    async def pause_schedule(self, source_id: str) -> dict[str, Any]:
        handle = (await self._provider.get()).get_schedule_handle(
            ingestion_schedule_id(source_id)
        )
        try:
            await handle.pause(note="Paused by BoThesis administrator")
            return self._schedule_payload(await handle.describe())
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                raise WorkflowExecutionNotFoundError(source_id) from exc
            raise

    async def resume_schedule(self, source_id: str) -> dict[str, Any]:
        handle = (await self._provider.get()).get_schedule_handle(
            ingestion_schedule_id(source_id)
        )
        try:
            await handle.unpause(note="Resumed by BoThesis administrator")
            return self._schedule_payload(await handle.describe())
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                raise WorkflowExecutionNotFoundError(source_id) from exc
            raise

    async def delete_schedule(self, source_id: str) -> None:
        handle = (await self._provider.get()).get_schedule_handle(
            ingestion_schedule_id(source_id)
        )
        try:
            await handle.delete()
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise

    def _schedule(
        self, input: IngestionWorkflowInput, values: dict[str, Any]
    ) -> Schedule:
        schedule_type = str(values.get("schedule_type") or "cron").strip().casefold()
        expression = str(values.get("cron_expression") or "").strip()
        if not expression:
            raise ValueError("schedule expression is required")
        if schedule_type == "cron":
            spec = ScheduleSpec(
                cron_expressions=[expression],
                time_zone_name=(str(values.get("timezone") or "UTC").strip()),
            )
        elif schedule_type == "interval":
            try:
                seconds = int(expression)
            except ValueError as exc:
                raise ValueError(
                    "interval schedule expression must be seconds"
                ) from exc
            if seconds < 1:
                raise ValueError("interval schedule must be positive")
            spec = ScheduleSpec(
                intervals=[ScheduleIntervalSpec(every=timedelta(seconds=seconds))]
            )
        else:
            raise ValueError("schedule_type must be cron or interval")
        overlap = str(values.get("overlap_policy") or "skip").strip().casefold()
        if overlap not in _OVERLAP_POLICIES:
            raise ValueError("unsupported overlap policy")
        enabled = values.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("schedule enabled must be a boolean")
        return Schedule(
            action=ScheduleActionStartWorkflow(
                INGESTION_WORKFLOW_NAME,
                input,
                id=ingestion_workflow_id(input.source_id),
                task_queue=self._settings.task_queue,
                typed_search_attributes=self._search_attributes(input),
                static_summary=f"Scheduled {input.connector_key} ingestion",
            ),
            spec=spec,
            policy=SchedulePolicy(
                overlap=_OVERLAP_POLICIES[overlap],
                catchup_window=timedelta(minutes=5),
                pause_on_failure=False,
            ),
            state=ScheduleState(paused=not enabled),
        )

    @staticmethod
    def _search_attributes(input: IngestionWorkflowInput) -> TypedSearchAttributes:
        pairs = [
            SearchAttributePair(_TENANT_ID, input.tenant_id),
            SearchAttributePair(_INGESTION_SOURCE_ID, input.source_id),
            SearchAttributePair(_CONNECTOR_KEY, input.connector_key),
            SearchAttributePair(_WORKFLOW_CATEGORY, "ingestion"),
            SearchAttributePair(_TRIGGER_TYPE, input.trigger_type),
        ]
        if input.integration_connection_id:
            pairs.append(SearchAttributePair(_INTEGRATION_CONNECTION_ID, input.integration_connection_id))
        return TypedSearchAttributes(pairs)

    @staticmethod
    def _visibility_query(
        *,
        tenant_id: str,
        status: str | None,
        source_id: str | None,
        integration_connection_id: str | None,
    ) -> str:
        clauses = [
            f"WorkflowType = '{INGESTION_WORKFLOW_NAME}'",
            f"TenantId = '{_visibility_literal(tenant_id)}'",
        ]
        if source_id:
            clauses.append(f"IngestionSourceId = '{_visibility_literal(source_id)}'")
        if integration_connection_id:
            clauses.append(f"IntegrationConnectionId = '{_visibility_literal(integration_connection_id)}'")
        if status:
            normalized = status.strip().casefold()
            if normalized not in _STATUS_QUERY_VALUES:
                raise ValueError("unsupported workflow status")
            clauses.append(f"ExecutionStatus = '{_STATUS_QUERY_VALUES[normalized]}'")
        return " AND ".join(clauses)

    @staticmethod
    def _execution_payload(
        execution: WorkflowExecution | WorkflowExecutionDescription,
    ) -> dict[str, Any]:
        status = execution.status.name.casefold() if execution.status else "unknown"
        if status == "canceled":
            status = "cancelled"
        return {
            "id": execution.id,
            "workflow_id": execution.id,
            "run_id": execution.run_id,
            "workflow_type": execution.workflow_type,
            "status": status,
            "source_id": execution.typed_search_attributes.get(_INGESTION_SOURCE_ID),
            "integration_connection_id": execution.typed_search_attributes.get(_INTEGRATION_CONNECTION_ID),
            "tenant_id": execution.typed_search_attributes.get(_TENANT_ID),
            "connector_key": execution.typed_search_attributes.get(_CONNECTOR_KEY),
            "trigger_type": execution.typed_search_attributes.get(_TRIGGER_TYPE),
            "started_at": execution.start_time.isoformat(),
            "finished_at": (
                execution.close_time.isoformat() if execution.close_time else None
            ),
            "history_length": execution.history_length,
        }

    @staticmethod
    def _schedule_payload(description: ScheduleDescription) -> dict[str, Any]:
        schedule = description.schedule
        spec = schedule.spec
        if spec.intervals:
            schedule_type = "interval"
            expression = str(round(spec.intervals[0].every.total_seconds()))
        else:
            schedule_type = "cron"
            expression = spec.cron_expressions[0] if spec.cron_expressions else ""
        overlap = {
            ScheduleOverlapPolicy.SKIP: "skip",
            ScheduleOverlapPolicy.BUFFER_ONE: "queue",
            ScheduleOverlapPolicy.CANCEL_OTHER: "replace",
        }.get(schedule.policy.overlap, schedule.policy.overlap.name.casefold())
        return {
            "id": description.id,
            "schedule_type": schedule_type,
            "cron_expression": expression,
            "timezone": spec.time_zone_name,
            "enabled": not schedule.state.paused,
            "paused": schedule.state.paused,
            "overlap_policy": overlap,
            "next_run_at": (
                description.info.next_action_times[0].isoformat()
                if description.info.next_action_times
                else None
            ),
            "last_run_at": (
                description.info.recent_actions[-1].scheduled_at.isoformat()
                if description.info.recent_actions
                else None
            ),
            "num_actions": description.info.num_actions,
            "num_actions_skipped_overlap": (
                description.info.num_actions_skipped_overlap
            ),
        }

    @staticmethod
    def _progress_payload(progress: IngestionProgress) -> dict[str, Any]:
        return {
            "phase": progress.phase,
            "discovered_count": progress.discovered_count,
            "processed_count": progress.processed_count,
            "indexed_count": progress.indexed_count,
            "deleted_count": progress.deleted_count,
            "failed_count": progress.failed_count,
        }


def _visibility_literal(value: str) -> str:
    return value.replace("'", "''")


__all__ = ["TemporalWorkflowService"]
