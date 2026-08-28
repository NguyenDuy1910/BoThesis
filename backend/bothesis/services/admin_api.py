"""Transactional application service for the tenant Admin control plane."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from temporalio.service import RPCError

from bothesis.db.engine import get_session_factory, session_scope
from bothesis.document_index.vector_store import VectorStore
from bothesis.services import (
    AccessRequestService,
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminItemService,
    AdminNotFoundError,
    AdminService,
    AdminValidationError,
    AuditService,
    AuthContext,
    CollectionAccessService,
    GroupService,
    PluginService,
    RequestIdentity,
    RoleService,
    SOURCE_MANAGE_PERMISSION,
    TenantService,
    UserService,
    require_tenant_permission,
)
from bothesis.services.request_identity import resolve_auth_context
from bothesis.workflow import (
    IngestionWorkflowInput,
    WorkflowExecutionNotFoundError,
)
from bothesis.workflow.service import TemporalWorkflowService


class AdminApiService:
    """Own request transactions and delegate admin work to focused services."""

    def __init__(self, *, allow_insecure_development_identity: bool) -> None:
        self._allow_insecure_development_identity = allow_insecure_development_identity
        self._session_factory: Any | None = None
        self._workflows = TemporalWorkflowService()

    async def overview(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AdminService(session).overview(actor)

    async def list_spaces(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).list_spaces(actor)

    async def get_space(self, identity: RequestIdentity, tenant_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).get_space(actor, tenant_id)

    async def update_space(
        self, identity: RequestIdentity, tenant_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).update_space(actor, tenant_id, **changes)

    async def list_users(self, identity: RequestIdentity, **filters: Any) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).list_users(actor, **filters)

    async def create_user(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).create_user(actor, **values)

    async def get_user(self, identity: RequestIdentity, user_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).get_user(actor, user_id)

    async def update_user(
        self, identity: RequestIdentity, user_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).update_user(actor, user_id, **changes)

    async def list_permissions(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).list_permissions(actor)

    async def list_roles(self, identity: RequestIdentity, **filters: Any) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).list_roles(actor, **filters)

    async def create_role(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).create_role(actor, **values)

    async def get_role(self, identity: RequestIdentity, role_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).get_role(actor, role_id)

    async def update_role(
        self, identity: RequestIdentity, role_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).update_role(actor, role_id, **changes)

    async def disable_role(self, identity: RequestIdentity, role_id: UUID) -> None:
        async with self._request(identity) as (session, actor):
            await RoleService(session).disable_role(actor, role_id)

    async def list_groups(self, identity: RequestIdentity, **filters: Any) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).list_groups(actor, **filters)

    async def create_group(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).create_group(actor, **values)

    async def get_group(self, identity: RequestIdentity, group_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).get_group(actor, group_id)

    async def update_group(
        self, identity: RequestIdentity, group_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).update_group(actor, group_id, **changes)

    async def replace_group_members(
        self, identity: RequestIdentity, group_id: UUID, user_ids: list[UUID]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).replace_members(actor, group_id, user_ids)

    async def delete_group(self, identity: RequestIdentity, group_id: UUID) -> None:
        async with self._request(identity) as (session, actor):
            await GroupService(session).delete_group(actor, group_id)

    async def plugin_capabilities(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).capabilities(actor)

    async def list_plugin_connections(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).list_connections(actor, **filters)

    async def create_plugin_connection(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).create_connection(actor, **values)

    async def get_plugin_connection(
        self, identity: RequestIdentity, connection_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).get_connection(actor, connection_id)

    async def update_plugin_connection(
        self, identity: RequestIdentity, connection_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).update_connection(actor, connection_id, **changes)

    async def delete_plugin_connection(
        self, identity: RequestIdentity, connection_id: UUID
    ) -> None:
        async with self._request(identity) as (session, actor):
            binding_ids: list[str] = []
            page = 1
            while True:
                bindings = await self._plugins(session).list_bindings(
                    actor,
                    connection_id=connection_id,
                    page=page,
                    page_size=100,
                )
                binding_ids.extend(binding["id"] for binding in bindings["items"])
                if len(binding_ids) >= bindings["total"]:
                    break
                page += 1
            await self._plugins(session).delete_connection(actor, connection_id)
        await asyncio.gather(
            *(
                self._workflows.delete_schedule(binding_id)
                for binding_id in binding_ids
            )
        )

    async def validate_plugin_connection(
        self, identity: RequestIdentity, connection_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).validate_connection(actor, connection_id)

    async def list_plugin_bindings(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            result = await self._plugins(session).list_bindings(actor, **filters)
        schedules = await asyncio.gather(
            *(
                self._workflows.describe_schedule(binding["id"])
                for binding in result["items"]
            )
        )
        for binding, schedule in zip(result["items"], schedules, strict=True):
            binding["schedule"] = schedule
        return result

    async def create_plugin_binding(
        self, identity: RequestIdentity, connection_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        values = dict(values)
        schedule = values.pop("schedule", None)
        async with self._request(identity) as (session, actor):
            binding = await self._plugins(session).create_binding(
                actor, connection_id, **values
            )
            workflow_input = self._workflow_input(binding, actor)
        if schedule is not None:
            binding["schedule"] = await self._upsert_schedule(
                workflow_input, schedule
            )
        return binding

    async def get_plugin_binding(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            binding = await self._plugins(session).get_binding(actor, binding_id)
        binding["schedule"] = await self._workflows.describe_schedule(str(binding_id))
        return binding

    async def update_plugin_binding(
        self, identity: RequestIdentity, binding_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        changes = dict(changes)
        schedule = changes.pop("schedule", None)
        clear_schedule = bool(changes.pop("clear_schedule", False))
        async with self._request(identity) as (session, actor):
            binding = await self._plugins(session).update_binding(
                actor, binding_id, **changes
            )
            workflow_input = self._workflow_input(binding, actor)
        if clear_schedule:
            await self._workflows.delete_schedule(str(binding_id))
            binding["schedule"] = None
        elif schedule is not None:
            binding["schedule"] = await self._upsert_schedule(
                workflow_input, schedule
            )
        else:
            binding["schedule"] = await self._workflows.describe_schedule(
                str(binding_id)
            )
        return binding

    async def delete_plugin_binding(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> None:
        async with self._request(identity) as (session, actor):
            await self._plugins(session).delete_binding(actor, binding_id)
        await self._workflows.delete_schedule(str(binding_id))

    async def sync_plugin_binding(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            binding = await self._plugins(session).get_binding(actor, binding_id)
            workflow_input = self._workflow_input(binding, actor)
        result = await self._workflows.start_ingestion(workflow_input)
        async with self._request(identity) as (session, actor):
            await AuditService(session).record(
                actor,
                action="plugin.binding.sync_requested",
                resource_type="plugin_binding",
                resource_id=str(binding_id),
                details={
                    "workflow_id": result["workflow_id"],
                    "run_id": result["run_id"],
                    "started": result["started"],
                },
            )
        return result

    async def list_ingestion_jobs(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            del session
            tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return await self._workflows.list_ingestions(
            tenant_id=str(tenant_id),
            **{
                key: str(value) if isinstance(value, UUID) else value
                for key, value in filters.items()
            },
        )

    async def get_ingestion_job(
        self, identity: RequestIdentity, workflow_id: str
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            del session
            tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        result = await self._describe_workflow(workflow_id)
        if result["tenant_id"] != str(tenant_id):
            raise AdminNotFoundError(f"ingestion workflow not found: {workflow_id}")
        return result

    async def retry_ingestion_job(
        self, identity: RequestIdentity, workflow_id: str
    ) -> dict[str, Any]:
        previous = await self.get_ingestion_job(identity, workflow_id)
        if previous["status"] not in {
            "failed",
            "cancelled",
            "terminated",
            "timed_out",
        }:
            raise AdminConflictError("only closed unsuccessful workflows can be retried")
        return await self.sync_plugin_binding(
            identity, UUID(str(previous["binding_id"]))
        )

    async def cancel_ingestion_job(
        self, identity: RequestIdentity, workflow_id: str
    ) -> dict[str, Any]:
        current = await self.get_ingestion_job(identity, workflow_id)
        if current["status"] != "running":
            raise AdminConflictError("only running workflows can be cancelled")
        return await self._workflows.cancel_ingestion(workflow_id)

    async def list_binding_workflows(
        self, identity: RequestIdentity, binding_id: UUID, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            await self._plugins(session).get_binding(actor, binding_id)
            tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return await self._workflows.list_ingestions(
            tenant_id=str(tenant_id),
            binding_id=str(binding_id),
            **filters,
        )

    async def get_binding_workflow(
        self,
        identity: RequestIdentity,
        binding_id: UUID,
        workflow_id: str,
    ) -> dict[str, Any]:
        result = await self.get_ingestion_job(identity, workflow_id)
        if result["binding_id"] != str(binding_id):
            raise AdminNotFoundError(f"ingestion workflow not found: {workflow_id}")
        return result

    async def get_binding_status(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            binding = await self._plugins(session).get_binding(actor, binding_id)
            tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return {
            "binding_id": str(binding_id),
            "binding_status": binding["status"],
            "last_synced_at": binding["last_synced_at"],
            "last_indexed_at": binding["last_indexed_at"],
            "workflow": await self._workflows.latest_ingestion(
                tenant_id=str(tenant_id), binding_id=str(binding_id)
            ),
        }

    async def get_binding_schedule(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> dict[str, Any]:
        await self.get_plugin_binding(identity, binding_id)
        schedule = await self._workflows.describe_schedule(str(binding_id))
        if schedule is None:
            raise AdminNotFoundError(f"ingestion schedule not found: {binding_id}")
        return schedule

    async def set_binding_schedule(
        self,
        identity: RequestIdentity,
        binding_id: UUID,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            binding = await self._plugins(session).get_binding(actor, binding_id)
            workflow_input = self._workflow_input(binding, actor)
        return await self._upsert_schedule(workflow_input, values)

    async def pause_binding_schedule(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> dict[str, Any]:
        await self.get_plugin_binding(identity, binding_id)
        return await self._schedule_operation(
            self._workflows.pause_schedule(binding_id=str(binding_id))
        )

    async def resume_binding_schedule(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> dict[str, Any]:
        await self.get_plugin_binding(identity, binding_id)
        return await self._schedule_operation(
            self._workflows.resume_schedule(binding_id=str(binding_id))
        )

    async def delete_binding_schedule(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> None:
        await self.get_plugin_binding(identity, binding_id)
        await self._workflows.delete_schedule(str(binding_id))

    async def list_items(self, identity: RequestIdentity, **filters: Any) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.list_items(actor, **filters)

    async def create_collection(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.create_collection(actor, **values)

    async def get_item(self, identity: RequestIdentity, item_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.get_item(actor, item_id)

    async def update_collection(
        self,
        identity: RequestIdentity,
        item_id: UUID,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.update_collection(
                    actor,
                    item_id,
                    title=changes.get("title"),
                    description=changes.get("description"),
                    description_provided="description" in changes,
                )

    async def update_item(
        self, identity: RequestIdentity, item_id: UUID, status: str
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.update_status(actor, item_id, status=status)

    async def retry_item(self, identity: RequestIdentity, item_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                result = await service.retry_item(actor, item_id)
        binding_id = result.pop("binding_id", None)
        if binding_id is not None:
            result["sync_run"] = await self.sync_plugin_binding(
                identity, UUID(binding_id)
            )
        return result

    async def delete_item(self, identity: RequestIdentity, item_id: UUID) -> None:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                await service.delete_item(actor, item_id)

    async def list_collection_access(
        self, identity: RequestIdentity, item_id: UUID, **filters: Any
    ) -> dict[str, object]:
        async with self._request(identity) as (session, actor):
            return await CollectionAccessService(session).list_grants(
                item_id, actor=actor, **filters
            )

    async def grant_collection_access(
        self, identity: RequestIdentity, item_id: UUID, values: dict[str, Any]
    ) -> dict[str, object]:
        async with self._request(identity) as (session, actor):
            grant = await CollectionAccessService(session).grant(item_id, actor=actor, **values)
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
            return CollectionAccessService._payload(grant)

    async def revoke_collection_access(
        self,
        identity: RequestIdentity,
        item_id: UUID,
        *,
        principal_type: str,
        principal_id: UUID,
    ) -> None:
        async with self._request(identity) as (session, actor):
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

    async def list_access_requests(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).list_requests(actor, **filters)

    async def create_access_request(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).create_request(actor, **values)

    async def get_access_request(
        self, identity: RequestIdentity, request_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).get_request(actor, request_id)

    async def decide_access_request(
        self, identity: RequestIdentity, request_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).decide_request(
                actor, request_id, **values
            )

    async def list_audit_logs(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AuditService(session).list_events(actor, **filters)

    @staticmethod
    def _workflow_input(
        binding: dict[str, Any], actor: AuthContext
    ) -> IngestionWorkflowInput:
        if actor.tenant_id is None:
            raise AdminNotFoundError("tenant context is required")
        connection = binding["connection"]
        return IngestionWorkflowInput(
            binding_id=str(binding["id"]),
            tenant_id=str(actor.tenant_id),
            connection_id=str(binding["connection_id"]),
            plugin_key=str(connection["plugin_key"]),
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

    @asynccontextmanager
    async def _request(
        self, identity: RequestIdentity
    ) -> AsyncIterator[tuple[Any, AuthContext]]:
        if self._session_factory is None:
            self._session_factory = get_session_factory()
        try:
            async with session_scope(self._session_factory) as session:
                actor = await resolve_auth_context(
                    identity,
                    session,
                    allow_insecure_development_identity=(
                        self._allow_insecure_development_identity
                    ),
                )
                yield session, actor
        except IntegrityError as exc:
            raise AdminConflictError(
                "the requested change conflicts with durable state"
            ) from exc

    @staticmethod
    def _plugins(session: Any) -> PluginService:
        return PluginService(
            session,
            credential_encryption_key=os.getenv("BOTHESIS_PLUGIN_ENCRYPTION_KEY"),
        )

    @staticmethod
    @asynccontextmanager
    async def _item_service(session: Any) -> AsyncIterator[AdminItemService]:
        store = VectorStore(
            collection_name=os.getenv("QDRANT_COLLECTION"),
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            timeout=20,
        )
        try:
            yield AdminItemService(
                session,
                plugin_encryption_key=os.getenv("BOTHESIS_PLUGIN_ENCRYPTION_KEY"),
                vector_store=store,
            )
        finally:
            await store.aclose()


__all__ = ["AdminApiService"]
