"""Transactional application service for Connections, Sources, and their runs.

Three layers meet here and nowhere else: Connection state in PostgreSQL, the
provider authorization flow, and the Temporal schedules and executions that
actually run a Source. Keeping them in one unit-of-work owner is what lets
deleting a connection also delete the schedules that would otherwise keep
firing against a credential that no longer exists.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.service import RPCError

from config import IntegrationConfig

from bothesis.db.engine import SessionFactory, session_scope
from bothesis.integrations.registry import ConnectionProviderRegistry
from bothesis.services.audit import AuditService
from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services.ingestion_sources import IngestionSourceService
from bothesis.services.integration_authorization import (
    IntegrationAuthorizationService,
)
from bothesis.services.integration_connections import IntegrationConnectionService
from bothesis.services import (
    CONNECTION_ERROR,
    SOURCE_MANAGE_PERMISSION,
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    AuthContext,
    AuthorizationStart,
    CompletedAuthorization,
    ConnectionAuthorizationRequiredError,
    require_tenant_permission,
)
from bothesis.services.workflow import (
    IngestionWorkflowInput,
    WorkflowExecutionNotFoundError,
)
from bothesis.services.workflow.service import TemporalWorkflowService

RETRYABLE_WORKFLOW_STATUSES = frozenset(
    {"failed", "cancelled", "terminated", "timed_out"}
)


class IntegrationConsoleService:
    """Own integration request transactions and their workflow side effects."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        workflows: TemporalWorkflowService,
        integration: IntegrationConfig,
        providers: ConnectionProviderRegistry,
        authorization: IntegrationAuthorizationService,
    ) -> None:
        self._sessions = session_factory
        self._workflows = workflows
        self._integration = integration
        self._providers = providers
        self._authorization = authorization

    # -- Catalogue ----------------------------------------------------------

    async def connector_capabilities(self, actor: AuthContext) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).capabilities(actor)

    # -- Connections --------------------------------------------------------

    async def list_connections(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).list_connections(actor, **filters)

    async def create_connection(
        self, actor: AuthContext, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).create_connection(actor, **values)

    async def get_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).get_connection(
                actor, integration_connection_id
            )

    async def update_connection(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).update_connection(
                actor, integration_connection_id, **changes
            )

    async def disconnect_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        """Revoke the grant and stop every schedule built on it."""

        async with self._unit_of_work() as session:
            source_ids = await self._connection_source_ids(
                session, actor, integration_connection_id
            )
            result = await self._connections(session).disconnect_connection(
                actor, integration_connection_id
            )
        await self._pause_schedules(source_ids)
        return result

    async def delete_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> None:
        """Delete a connection and every ingestion schedule that depended on it."""

        async with self._unit_of_work() as session:
            source_ids = await self._connection_source_ids(
                session, actor, integration_connection_id
            )
            await self._connections(session).delete_connection(
                actor, integration_connection_id
            )
        await asyncio.gather(
            *(self._workflows.delete_schedule(source_id) for source_id in source_ids)
        )

    async def validate_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        async def work() -> dict[str, Any]:
            async with self._unit_of_work() as session:
                return await self._connections(session).validate_connection(
                    actor, integration_connection_id
                )

        return await self._recording_health(integration_connection_id, work)

    async def list_connection_resources(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        **filters: Any,
    ) -> dict[str, Any]:
        async def work() -> dict[str, Any]:
            async with self._unit_of_work() as session:
                return await self._connections(session).list_resources(
                    actor, integration_connection_id, **filters
                )

        return await self._recording_health(integration_connection_id, work)

    # -- Authorization ------------------------------------------------------

    def start_authorization(
        self,
        actor: AuthContext,
        *,
        connector_key: str,
        owner_type: str,
        integration_connection_id: UUID | None = None,
    ) -> AuthorizationStart:
        return self._authorization.start(
            actor,
            connector_key=connector_key,
            owner_type=owner_type,
            integration_connection_id=integration_connection_id,
        )

    def read_authorization_state(self, state: str) -> CompletedAuthorization:
        """Recover who started an authorization before anything is exchanged."""

        return self._authorization.read_state(state)

    async def complete_authorization(self, *, code: str, state: str) -> dict[str, Any]:
        """Turn a provider callback into a stored Connection.

        The caller is recovered from the signed state rather than from a header:
        the browser arrives here straight from the provider and carries no
        BoThesis token, so the state is the only thing that can say who began
        this and what they were allowed to do.
        """

        completed = self._authorization.read_state(state)
        grant = await self._authorization.exchange(completed, code=code)
        async with self._unit_of_work() as session:
            actor = await IdentityStoreService(session).get_context(
                completed.user_id, tenant_id=completed.tenant_id
            )
            return await self._connections(session).record_authorization(
                actor,
                connector_key=completed.pending.connector_key,
                grant=grant,
                owner_type=completed.pending.owner_type,
                integration_connection_id=completed.connection_id,
            )

    def authorization_client_origin(self) -> str:
        return self._authorization.client_origin

    # -- Sources ------------------------------------------------------------

    async def list_sources(self, actor: AuthContext, **filters: Any) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            result = await self._sources(session).list_sources(actor, **filters)
        schedules = await asyncio.gather(
            *(
                self._workflows.describe_schedule(source["id"])
                for source in result["items"]
            )
        )
        for source, schedule in zip(result["items"], schedules, strict=True):
            source["schedule"] = schedule
        return result

    async def create_source(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        values = dict(values)
        schedule = values.pop("schedule", None)
        # Nothing syncs on its own unless a schedule was asked for.
        values["sync_mode"] = "scheduled" if schedule is not None else "manual"
        async with self._unit_of_work() as session:
            source = await self._sources(session).create_source(
                actor, integration_connection_id, **values
            )
            workflow_input = self._workflow_input(source, actor)
        if schedule is not None:
            source["schedule"] = await self._upsert_schedule(workflow_input, schedule)
        return source

    async def get_source(self, actor: AuthContext, source_id: UUID) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            source = await self._sources(session).get_source(actor, source_id)
        source["schedule"] = await self._workflows.describe_schedule(str(source_id))
        return source

    async def update_source(
        self, actor: AuthContext, source_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        changes = dict(changes)
        schedule = changes.pop("schedule", None)
        clear_schedule = bool(changes.pop("clear_schedule", False))
        if clear_schedule:
            changes["sync_mode"] = "manual"
        elif schedule is not None:
            changes["sync_mode"] = "scheduled"
        async with self._unit_of_work() as session:
            source = await self._sources(session).update_source(
                actor, source_id, **changes
            )
            workflow_input = self._workflow_input(source, actor)
        if clear_schedule:
            await self._workflows.delete_schedule(str(source_id))
            source["schedule"] = None
        elif schedule is not None:
            source["schedule"] = await self._upsert_schedule(workflow_input, schedule)
        else:
            source["schedule"] = await self._workflows.describe_schedule(str(source_id))
        return source

    async def delete_source(self, actor: AuthContext, source_id: UUID) -> None:
        async with self._unit_of_work() as session:
            await self._sources(session).delete_source(actor, source_id)
        await self._workflows.delete_schedule(str(source_id))

    async def ingest_source(
        self, actor: AuthContext, source_id: UUID
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            source = await self._sources(session).get_source(actor, source_id)
            workflow_input = self._workflow_input(source, actor)
        result = await self._workflows.start_ingestion(workflow_input)
        async with self._unit_of_work() as session:
            await AuditService(session).record(
                actor,
                action="ingestion.source.requested",
                resource_type="ingestion_source",
                resource_id=str(source_id),
                details={
                    "workflow_id": result["workflow_id"],
                    "run_id": result["run_id"],
                    "started": result["started"],
                },
            )
        return result

    # -- Ingestion jobs -----------------------------------------------------

    async def list_ingestion_jobs(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return await self._workflows.list_ingestions(
            tenant_id=str(tenant_id),
            **{
                key: str(value) if isinstance(value, UUID) else value
                for key, value in filters.items()
            },
        )

    async def get_ingestion_job(
        self, actor: AuthContext, workflow_id: str
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        result = await self._describe_workflow(workflow_id)
        if result["tenant_id"] != str(tenant_id):
            raise AdminNotFoundError(f"ingestion workflow not found: {workflow_id}")
        return result

    async def retry_ingestion_job(
        self, actor: AuthContext, workflow_id: str
    ) -> dict[str, Any]:
        previous = await self.get_ingestion_job(actor, workflow_id)
        if previous["status"] not in RETRYABLE_WORKFLOW_STATUSES:
            raise AdminConflictError("only closed unsuccessful workflows can be retried")
        return await self.ingest_source(actor, UUID(str(previous["source_id"])))

    async def cancel_ingestion_job(
        self, actor: AuthContext, workflow_id: str
    ) -> dict[str, Any]:
        current = await self.get_ingestion_job(actor, workflow_id)
        if current["status"] != "running":
            raise AdminConflictError("only running workflows can be cancelled")
        return await self._workflows.cancel_ingestion(workflow_id)

    async def list_source_workflows(
        self, actor: AuthContext, source_id: UUID, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            await self._sources(session).get_source(actor, source_id)
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return await self._workflows.list_ingestions(
            tenant_id=str(tenant_id),
            source_id=str(source_id),
            **filters,
        )

    async def get_source_workflow(
        self, actor: AuthContext, source_id: UUID, workflow_id: str
    ) -> dict[str, Any]:
        result = await self.get_ingestion_job(actor, workflow_id)
        if result["source_id"] != str(source_id):
            raise AdminNotFoundError(f"ingestion workflow not found: {workflow_id}")
        return result

    async def get_source_status(
        self, actor: AuthContext, source_id: UUID
    ) -> dict[str, Any]:
        """The source's own state, and separately the state of its last run."""

        async with self._unit_of_work() as session:
            source = await self._sources(session).get_source(actor, source_id)
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return {
            "source_id": str(source_id),
            "source_status": source["status"],
            "source_status_detail": source["status_detail"],
            "connection_status": source["integration_connection"]["status"],
            "last_ingested_at": source["last_ingested_at"],
            "last_indexed_at": source["last_indexed_at"],
            "workflow": await self._workflows.latest_ingestion(
                tenant_id=str(tenant_id), source_id=str(source_id)
            ),
        }

    # -- Ingestion schedules ------------------------------------------------

    async def get_source_schedule(
        self, actor: AuthContext, source_id: UUID
    ) -> dict[str, Any]:
        await self.get_source(actor, source_id)
        schedule = await self._workflows.describe_schedule(str(source_id))
        if schedule is None:
            raise AdminNotFoundError(f"ingestion schedule not found: {source_id}")
        return schedule

    async def set_source_schedule(
        self, actor: AuthContext, source_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            source = await self._sources(session).update_source(
                actor, source_id, sync_mode="scheduled"
            )
            workflow_input = self._workflow_input(source, actor)
        return await self._upsert_schedule(workflow_input, values)

    async def pause_source_schedule(
        self, actor: AuthContext, source_id: UUID
    ) -> dict[str, Any]:
        await self.get_source(actor, source_id)
        return await self._schedule_operation(
            self._workflows.pause_schedule(source_id=str(source_id))
        )

    async def resume_source_schedule(
        self, actor: AuthContext, source_id: UUID
    ) -> dict[str, Any]:
        await self.get_source(actor, source_id)
        return await self._schedule_operation(
            self._workflows.resume_schedule(source_id=str(source_id))
        )

    async def delete_source_schedule(
        self, actor: AuthContext, source_id: UUID
    ) -> None:
        async with self._unit_of_work() as session:
            await self._sources(session).update_source(
                actor, source_id, sync_mode="manual"
            )
        await self._workflows.delete_schedule(str(source_id))

    # -- Internals ----------------------------------------------------------

    @asynccontextmanager
    async def _unit_of_work(self) -> AsyncIterator[AsyncSession]:
        try:
            async with session_scope(self._sessions) as session:
                yield session
        except IntegrityError as exc:
            raise AdminConflictError(
                "the requested change conflicts with durable state"
            ) from exc

    async def _recording_health(
        self,
        integration_connection_id: UUID,
        work: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Run one attempt, and keep what it learned about the connection.

        A failure rolls its own transaction back, so the state it discovered is
        written in a second one. Without this the page would show a healthy
        connection that fails every time it is used, with no reconnect offered.
        """

        try:
            return await work()
        except ConnectionAuthorizationRequiredError as exc:
            await self._record_health(
                integration_connection_id, status=exc.status, detail=exc.detail
            )
            raise
        except AdminExternalUnavailableError as exc:
            await self._record_health(
                integration_connection_id, status=CONNECTION_ERROR, detail=str(exc)
            )
            raise

    async def _record_health(
        self, integration_connection_id: UUID, *, status: str, detail: str
    ) -> None:
        try:
            async with self._unit_of_work() as session:
                await self._connections(session).record_health(
                    integration_connection_id, status=status, detail=detail
                )
        except Exception:
            # The original failure is what the caller needs to see. Losing the
            # note about it is worse than nothing, not worse than the wrong
            # error.
            return

    async def _connection_source_ids(
        self,
        session: AsyncSession,
        actor: AuthContext,
        integration_connection_id: UUID,
    ) -> list[str]:
        source_ids: list[str] = []
        page = 1
        while True:
            sources = await self._sources(session).list_sources(
                actor,
                integration_connection_id=integration_connection_id,
                page=page,
                page_size=100,
            )
            source_ids.extend(source["id"] for source in sources["items"])
            if len(source_ids) >= sources["total"]:
                return source_ids
            page += 1

    async def _pause_schedules(self, source_ids: list[str]) -> None:
        """Stop scheduled runs that can no longer authenticate.

        A missing schedule is the same outcome as a paused one, so it is not an
        error worth failing a disconnect over.
        """

        for source_id in source_ids:
            try:
                await self._workflows.pause_schedule(source_id=source_id)
            except (WorkflowExecutionNotFoundError, RPCError):
                continue

    @staticmethod
    def _workflow_input(
        source: dict[str, Any], actor: AuthContext
    ) -> IngestionWorkflowInput:
        if actor.tenant_id is None:
            raise AdminNotFoundError("tenant context is required")
        connection = source["integration_connection"]
        return IngestionWorkflowInput(
            source_id=str(source["id"]),
            tenant_id=str(actor.tenant_id),
            integration_connection_id=str(source["integration_connection_id"]),
            connector_key=str(connection["connector_key"]),
        )

    async def _upsert_schedule(
        self, input: IngestionWorkflowInput, values: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return await self._workflows.upsert_schedule(input, values)
        except ValueError as exc:
            raise AdminValidationError(str(exc)) from exc
        except RPCError as exc:
            raise AdminExternalUnavailableError("Temporal is unavailable") from exc

    async def _describe_workflow(self, workflow_id: str) -> dict[str, Any]:
        try:
            return await self._workflows.describe_ingestion(workflow_id)
        except WorkflowExecutionNotFoundError as exc:
            raise AdminNotFoundError(
                f"ingestion workflow not found: {workflow_id}"
            ) from exc
        except RPCError as exc:
            raise AdminExternalUnavailableError("Temporal is unavailable") from exc

    @staticmethod
    async def _schedule_operation(
        operation: Awaitable[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            return await operation
        except WorkflowExecutionNotFoundError as exc:
            raise AdminNotFoundError("ingestion schedule not found") from exc
        except RPCError as exc:
            raise AdminExternalUnavailableError("Temporal is unavailable") from exc

    def _connections(self, session: AsyncSession) -> IntegrationConnectionService:
        return IntegrationConnectionService(
            session,
            providers=self._providers,
            credential_encryption_key=self._integration.credential_encryption_key,
        )

    def _sources(self, session: AsyncSession) -> IngestionSourceService:
        return IngestionSourceService(
            session,
            providers=self._providers,
            credential_encryption_key=self._integration.credential_encryption_key,
        )


__all__ = ["RETRYABLE_WORKFLOW_STATUSES", "IntegrationConsoleService"]
