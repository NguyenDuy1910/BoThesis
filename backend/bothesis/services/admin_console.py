"""Transactional application service for the tenant Admin control plane."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.service import RPCError

from config import IntegrationConfig, VectorIndexConfig

from bothesis.db.engine import SessionFactory, session_scope
from bothesis.document_index import ItemIndex
from bothesis.services import (
    SOURCE_MANAGE_PERMISSION,
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    AuthContext,
    require_tenant_permission,
)
from bothesis.services.access_requests import AccessRequestService
from bothesis.services.audit import AuditService
from bothesis.services.collection_access import CollectionAccessService
from bothesis.services.groups import GroupService
from bothesis.services.ingestion_sources import IngestionSourceService
from bothesis.services.integration_connections import IntegrationConnectionService
from bothesis.services.item_catalog import ItemCatalogService
from bothesis.services.item_ingestion import ItemIngestionService
from bothesis.services.roles import RoleService
from bothesis.services.tenants import TenantService
from bothesis.services.users import UserService
from bothesis.services.workflow import (
    IngestionWorkflowInput,
    WorkflowExecutionNotFoundError,
)
from bothesis.services.workflow.service import TemporalWorkflowService

RETRYABLE_WORKFLOW_STATUSES = frozenset(
    {"failed", "cancelled", "terminated", "timed_out"}
)


class AdminConsoleService:
    """Own admin request transactions and delegate work to focused services."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        workflows: TemporalWorkflowService,
        integration: IntegrationConfig,
        vector_index: VectorIndexConfig,
    ) -> None:
        self._sessions = session_factory
        self._workflows = workflows
        self._integration = integration
        self._vector_index = vector_index

    # -- Tenants ------------------------------------------------------------

    async def overview(self, actor: AuthContext) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await TenantService(session).overview(actor)

    async def list_spaces(self, actor: AuthContext) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await TenantService(session).list_tenants(actor)

    async def get_space(self, actor: AuthContext, tenant_id: UUID) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await TenantService(session).get_tenant(actor, tenant_id)

    async def update_space(
        self, actor: AuthContext, tenant_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await TenantService(session).update_tenant(
                actor, tenant_id, **changes
            )

    # -- Users, roles, groups ----------------------------------------------

    async def list_users(self, actor: AuthContext, **filters: Any) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await UserService(session).list_users(actor, **filters)

    async def create_user(
        self, actor: AuthContext, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await UserService(session).create_user(actor, **values)

    async def get_user(self, actor: AuthContext, user_id: UUID) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await UserService(session).get_user(actor, user_id)

    async def update_user(
        self, actor: AuthContext, user_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await UserService(session).update_user(actor, user_id, **changes)

    async def list_permissions(self, actor: AuthContext) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await RoleService(session).list_permissions(actor)

    async def list_roles(self, actor: AuthContext, **filters: Any) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await RoleService(session).list_roles(actor, **filters)

    async def create_role(
        self, actor: AuthContext, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await RoleService(session).create_role(actor, **values)

    async def get_role(self, actor: AuthContext, role_id: UUID) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await RoleService(session).get_role(actor, role_id)

    async def update_role(
        self, actor: AuthContext, role_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await RoleService(session).update_role(actor, role_id, **changes)

    async def disable_role(self, actor: AuthContext, role_id: UUID) -> None:
        async with self._unit_of_work() as session:
            await RoleService(session).disable_role(actor, role_id)

    async def list_groups(self, actor: AuthContext, **filters: Any) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await GroupService(session).list_groups(actor, **filters)

    async def create_group(
        self, actor: AuthContext, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await GroupService(session).create_group(actor, **values)

    async def get_group(self, actor: AuthContext, group_id: UUID) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await GroupService(session).get_group(actor, group_id)

    async def update_group(
        self, actor: AuthContext, group_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await GroupService(session).update_group(actor, group_id, **changes)

    async def replace_group_members(
        self, actor: AuthContext, group_id: UUID, user_ids: list[UUID]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await GroupService(session).replace_members(
                actor, group_id, user_ids
            )

    async def delete_group(self, actor: AuthContext, group_id: UUID) -> None:
        async with self._unit_of_work() as session:
            await GroupService(session).delete_group(actor, group_id)

    # -- Integration connections -------------------------------------------

    async def connector_capabilities(self, actor: AuthContext) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).capabilities(actor)

    async def list_integration_connections(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).list_connections(actor, **filters)

    async def create_integration_connection(
        self, actor: AuthContext, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).create_connection(actor, **values)

    async def get_integration_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).get_connection(
                actor, integration_connection_id
            )

    async def update_integration_connection(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).update_connection(
                actor, integration_connection_id, **changes
            )

    async def delete_integration_connection(
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

    async def validate_integration_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await self._connections(session).validate_connection(
                actor, integration_connection_id
            )

    # -- Ingestion sources --------------------------------------------------

    async def list_ingestion_sources(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
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

    async def create_ingestion_source(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        values = dict(values)
        schedule = values.pop("schedule", None)
        async with self._unit_of_work() as session:
            source = await self._sources(session).create_source(
                actor, integration_connection_id, **values
            )
            workflow_input = self._workflow_input(source, actor)
        if schedule is not None:
            source["schedule"] = await self._upsert_schedule(workflow_input, schedule)
        return source

    async def get_ingestion_source(
        self, actor: AuthContext, source_id: UUID
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            source = await self._sources(session).get_source(actor, source_id)
        source["schedule"] = await self._workflows.describe_schedule(str(source_id))
        return source

    async def update_ingestion_source(
        self, actor: AuthContext, source_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        changes = dict(changes)
        schedule = changes.pop("schedule", None)
        clear_schedule = bool(changes.pop("clear_schedule", False))
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

    async def delete_ingestion_source(
        self, actor: AuthContext, source_id: UUID
    ) -> None:
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
        async with self._unit_of_work() as session:
            source = await self._sources(session).get_source(actor, source_id)
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return {
            "source_id": str(source_id),
            "source_status": source["status"],
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
        await self.get_ingestion_source(actor, source_id)
        schedule = await self._workflows.describe_schedule(str(source_id))
        if schedule is None:
            raise AdminNotFoundError(f"ingestion schedule not found: {source_id}")
        return schedule

    async def set_source_schedule(
        self, actor: AuthContext, source_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            source = await self._sources(session).get_source(actor, source_id)
            workflow_input = self._workflow_input(source, actor)
        return await self._upsert_schedule(workflow_input, values)

    async def pause_source_schedule(
        self, actor: AuthContext, source_id: UUID
    ) -> dict[str, Any]:
        await self.get_ingestion_source(actor, source_id)
        return await self._schedule_operation(
            self._workflows.pause_schedule(source_id=str(source_id))
        )

    async def resume_source_schedule(
        self, actor: AuthContext, source_id: UUID
    ) -> dict[str, Any]:
        await self.get_ingestion_source(actor, source_id)
        return await self._schedule_operation(
            self._workflows.resume_schedule(source_id=str(source_id))
        )

    async def delete_source_schedule(
        self, actor: AuthContext, source_id: UUID
    ) -> None:
        await self.get_ingestion_source(actor, source_id)
        await self._workflows.delete_schedule(str(source_id))

    # -- Items and Collections ---------------------------------------------

    async def list_items(self, actor: AuthContext, **filters: Any) -> dict[str, Any]:
        async with self._catalog() as (session, service):
            del session
            return await service.list_items(actor, **filters)

    async def create_collection(
        self, actor: AuthContext, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._catalog() as (session, service):
            del session
            return await service.create_collection(actor, **values)

    async def get_item(self, actor: AuthContext, item_id: UUID) -> dict[str, Any]:
        async with self._catalog() as (session, service):
            del session
            return await service.get_item(actor, item_id)

    async def update_collection(
        self, actor: AuthContext, item_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._catalog() as (session, service):
            del session
            return await service.update_collection(
                actor,
                item_id,
                title=changes.get("title"),
                description=changes.get("description"),
                description_provided="description" in changes,
            )

    async def update_item(
        self, actor: AuthContext, item_id: UUID, status: str
    ) -> dict[str, Any]:
        async with self._catalog() as (session, service):
            del session
            return await service.update_status(actor, item_id, status=status)

    async def retry_item(self, actor: AuthContext, item_id: UUID) -> dict[str, Any]:
        async with self._catalog() as (session, service):
            del session
            result = await service.retry_item(actor, item_id)
        ingestion_source_id = result.pop("ingestion_source_id", None)
        if ingestion_source_id is not None:
            result["ingestion_run"] = await self.ingest_source(
                actor, UUID(ingestion_source_id)
            )
        return result

    async def delete_item(self, actor: AuthContext, item_id: UUID) -> None:
        async with self._catalog() as (session, service):
            del session
            await service.delete_item(actor, item_id)

    # -- Collection access --------------------------------------------------

    async def list_collection_access(
        self, actor: AuthContext, item_id: UUID, **filters: Any
    ) -> dict[str, object]:
        async with self._unit_of_work() as session:
            return await CollectionAccessService(session).list_grants(
                item_id, actor=actor, **filters
            )

    async def grant_collection_access(
        self, actor: AuthContext, item_id: UUID, values: dict[str, Any]
    ) -> dict[str, object]:
        async with self._unit_of_work() as session:
            access = CollectionAccessService(session)
            grant = await access.grant(item_id, actor=actor, **values)
            await AuditService(session).record(
                actor,
                action="collection.access.granted",
                resource_type="collection",
                resource_id=str(item_id),
                details={
                    "principal_type": grant.principal_type,
                    "principal_id": str(grant.principal_id),
                    "role": grant.role,
                },
            )
            return access.grant_payload(grant)

    async def revoke_collection_access(
        self,
        actor: AuthContext,
        item_id: UUID,
        *,
        principal_type: str,
        principal_id: UUID,
    ) -> None:
        async with self._unit_of_work() as session:
            await CollectionAccessService(session).revoke(
                item_id,
                principal_type=principal_type,
                principal_id=principal_id,
                actor=actor,
            )
            await AuditService(session).record(
                actor,
                action="collection.access.revoked",
                resource_type="collection",
                resource_id=str(item_id),
                details={
                    "principal_type": principal_type,
                    "principal_id": str(principal_id),
                },
            )

    # -- Access requests and audit -----------------------------------------

    async def list_access_requests(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await AccessRequestService(session).list_requests(actor, **filters)

    async def create_access_request(
        self, actor: AuthContext, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await AccessRequestService(session).create_request(actor, **values)

    async def get_access_request(
        self, actor: AuthContext, request_id: UUID
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await AccessRequestService(session).get_request(actor, request_id)

    async def decide_access_request(
        self, actor: AuthContext, request_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await AccessRequestService(session).decide_request(
                actor, request_id, **values
            )

    async def list_audit_logs(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await AuditService(session).list_events(actor, **filters)

    # -- Internals ----------------------------------------------------------

    @asynccontextmanager
    async def _unit_of_work(self) -> AsyncIterator[AsyncSession]:
        """Commit one admin change, reporting write conflicts as conflicts."""

        try:
            async with session_scope(self._sessions) as session:
                yield session
        except IntegrityError as exc:
            raise AdminConflictError(
                "the requested change conflicts with durable state"
            ) from exc

    @asynccontextmanager
    async def _catalog(
        self,
    ) -> AsyncIterator[tuple[AsyncSession, ItemCatalogService]]:
        """Open a unit of work with an Item catalog bound to its own index."""

        index = ItemIndex(
            collection_name=self._vector_index.collection,
            url=self._vector_index.url,
            api_key=self._vector_index.api_key,
            timeout=self._vector_index.timeout_seconds,
        )
        try:
            async with self._unit_of_work() as session:
                yield session, ItemCatalogService(
                    session,
                    ingestion_service=ItemIngestionService(
                        self._sessions, index=index
                    ),
                )
        finally:
            await index.aclose()

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
            credential_encryption_key=self._integration.credential_encryption_key,
        )

    def _sources(self, session: AsyncSession) -> IngestionSourceService:
        return IngestionSourceService(
            session,
            credential_encryption_key=self._integration.credential_encryption_key,
        )


__all__ = ["AdminConsoleService"]
