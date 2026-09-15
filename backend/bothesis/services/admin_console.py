"""Transactional application service for the tenant Admin control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.engine import SessionFactory, session_scope
from bothesis.document_index import ItemIndex
from bothesis.services import (
    COLLECTION_SHARE_PERMISSION,
    AdminConflictError,
    AuthContext,
)
from bothesis.services.approval_request import ApprovalRequestService
from bothesis.services.audit import AuditService
from bothesis.services.dashboard.dashboard import DashboardService
from bothesis.services.identity_access.authorization import AuthorizationService
from bothesis.services.identity_access.role_assignments import RoleAssignmentService
from bothesis.services.identity_access.groups import GroupService
from bothesis.services.identity_access.roles import RoleService
from bothesis.services.identity_access.tenants import TenantService
from bothesis.services.identity_access.users import UserService
from bothesis.services.item_catalog import ItemCatalogService
from bothesis.services.item_ingestion import ItemIngestionService
from config import VectorIndexConfig


class AdminConsoleService:
    """Own admin request transactions and delegate work to focused services."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        vector_index: VectorIndexConfig,
    ) -> None:
        self._sessions = session_factory
        self._vector_index = vector_index

    # -- Tenants ------------------------------------------------------------

    async def overview(self, actor: AuthContext) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await DashboardService(session).overview(actor)

    async def platform_overview(self, actor: AuthContext) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await DashboardService(session).platform_overview(actor)

    async def list_platform_workspaces(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await DashboardService(session).list_platform_workspaces(
                actor, **filters
            )

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

    async def list_platform_users(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await UserService(session).list_platform_users(actor, **filters)

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

    @staticmethod
    async def _require_share(
        session: AsyncSession, actor: AuthContext, item_id: UUID
    ) -> None:
        """Only someone who may share this Collection may read or change who can."""

        await AuthorizationService(session).require_item(
            item_id, access=actor, permission=COLLECTION_SHARE_PERMISSION
        )

    async def list_collection_access(
        self, actor: AuthContext, item_id: UUID, **filters: Any
    ) -> dict[str, object]:
        async with self._unit_of_work() as session:
            await self._require_share(session, actor, item_id)
            return await RoleAssignmentService(session).list_collection_grants(
                item_id, **filters
            )

    async def grant_collection_access(
        self, actor: AuthContext, item_id: UUID, values: dict[str, Any]
    ) -> dict[str, object]:
        async with self._unit_of_work() as session:
            await self._require_share(session, actor, item_id)
            assignments = RoleAssignmentService(session)
            grant, role = await assignments.grant_collection_role(
                item_id, created_by_user_id=actor.user_id, **values
            )
            await AuditService(session).record(
                actor,
                action="collection.access.granted",
                resource_type="collection",
                resource_id=str(item_id),
                details={
                    "principal_type": grant.principal_type,
                    "principal_id": str(grant.principal_id),
                    "role_code": role.code,
                },
            )
            return assignments.grant_payload(grant, role)

    async def revoke_collection_access(
        self,
        actor: AuthContext,
        item_id: UUID,
        *,
        principal_type: str,
        principal_id: UUID,
    ) -> None:
        async with self._unit_of_work() as session:
            await self._require_share(session, actor, item_id)
            await RoleAssignmentService(session).revoke_collection_role(
                item_id,
                principal_type=principal_type,
                principal_id=principal_id,
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

    # -- Approval requests and audit ---------------------------------------

    async def list_approval_requests(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await ApprovalRequestService(session).list_requests(actor, **filters)

    async def create_approval_request(
        self, actor: AuthContext, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await ApprovalRequestService(session).create_request(actor, **values)

    async def get_approval_request(
        self, actor: AuthContext, request_id: UUID
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await ApprovalRequestService(session).get_request(actor, request_id)

    async def update_approval_request(
        self, actor: AuthContext, request_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await ApprovalRequestService(session).update_request(
                actor, request_id, **values
            )

    async def list_audit_logs(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await AuditService(session).list_events(actor, **filters)

    async def list_platform_audit_logs(
        self, actor: AuthContext, **filters: Any
    ) -> dict[str, Any]:
        async with self._unit_of_work() as session:
            return await AuditService(session).list_platform_events(actor, **filters)

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


__all__ = ["AdminConsoleService"]
