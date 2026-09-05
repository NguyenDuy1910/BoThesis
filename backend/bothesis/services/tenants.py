"""Tenant profile administration within the authenticated membership boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import (
    AccessRequest,
    Group,
    IntegrationConnection,
    Item,
    Role,
    Tenant,
    TenantMembership,
    User,
)
from bothesis.services.audit import AuditService
from bothesis.services import (
    ACTIVE_STATUS,
    ADMIN_PERMISSION,
    TENANT_MANAGE_PERMISSION,
    AdminNotFoundError,
    AuthContext,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)


class TenantService:
    """Read, update, and summarize the actor's durable tenant."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def list_tenants(self, actor: AuthContext) -> dict[str, Any]:
        tenant = await self._tenant(actor)
        return {
            "items": [_tenant_payload(tenant)],
            "total": 1,
            "page": 1,
            "page_size": 1,
        }

    async def overview(self, actor: AuthContext) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ADMIN_PERMISSION)
        tenant = await self._tenant(actor)
        metrics = {
            "active_users": await self._count(
                select(func.count())
                .select_from(TenantMembership)
                .join(User, User.id == TenantMembership.user_id)
                .where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.status == ACTIVE_STATUS,
                    TenantMembership.deleted_at.is_(None),
                    User.status == ACTIVE_STATUS,
                )
            ),
            "active_roles": await self._count(
                select(func.count()).select_from(Role).where(
                    Role.tenant_id == tenant_id,
                    Role.status == ACTIVE_STATUS,
                )
            ),
            "active_groups": await self._count(
                select(func.count()).select_from(Group).where(
                    Group.tenant_id == tenant_id,
                    Group.status == ACTIVE_STATUS,
                    Group.deleted_at.is_(None),
                )
            ),
            "active_integration_connections": await self._count(
                select(func.count()).select_from(IntegrationConnection).where(
                    IntegrationConnection.tenant_id == tenant_id,
                    IntegrationConnection.status == ACTIVE_STATUS,
                    IntegrationConnection.deleted_at.is_(None),
                )
            ),
            "items": await self._count(
                select(func.count()).select_from(Item).where(
                    Item.tenant_id == tenant_id,
                    Item.status != "deleted",
                    Item.deleted_at.is_(None),
                )
            ),
        }
        attention = {
            "pending_access_requests": await self._count(
                select(func.count()).select_from(AccessRequest).where(
                    AccessRequest.tenant_id == tenant_id,
                    AccessRequest.status == "pending",
                    AccessRequest.deleted_at.is_(None),
                )
            ),
            "failed_items": await self._count(
                select(func.count()).select_from(Item).where(
                    Item.tenant_id == tenant_id,
                    Item.status == "failed",
                    Item.deleted_at.is_(None),
                )
            ),
        }
        recent = await self._audit.list_events(actor, page=1, page_size=8)
        return {
            "tenant": {
                "id": str(tenant.id),
                "code": tenant.code,
                "name": tenant.name,
                "status": tenant.status,
                "updated_at": timestamp(tenant.updated_at),
            },
            "metrics": metrics,
            "attention": attention,
            "recent_activity": recent["items"],
            "generated_at": timestamp(await self._session.scalar(select(func.now()))),
        }

    async def get_tenant(self, actor: AuthContext, tenant_id: UUID) -> dict[str, Any]:
        trusted_tenant_id = require_tenant_permission(actor)
        if tenant_id != trusted_tenant_id:
            raise AdminNotFoundError(f"tenant not found: {tenant_id}")
        return _tenant_payload(await self._tenant(actor))

    async def update_tenant(
        self,
        actor: AuthContext,
        tenant_id: UUID,
        *,
        name: str | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        trusted_tenant_id = require_tenant_permission(
            actor, TENANT_MANAGE_PERMISSION
        )
        if tenant_id != trusted_tenant_id:
            raise AdminNotFoundError(f"tenant not found: {tenant_id}")
        tenant = await self._tenant(actor)
        changed: list[str] = []
        if name is not None:
            tenant.name = normalize_required_text(name, "tenant name", 255)
            changed.append("name")
        if settings is not None:
            tenant.settings = dict(settings)
            changed.append("settings")
        await self._session.flush()
        await self._audit.record(
            actor,
            action="tenant.updated",
            resource_type="tenant",
            resource_id=str(tenant.id),
            details={"changed_fields": changed},
        )
        return _tenant_payload(tenant)

    async def _tenant(self, actor: AuthContext) -> Tenant:
        tenant_id = require_tenant_permission(actor)
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            raise AdminNotFoundError(f"tenant not found: {tenant_id}")
        return tenant

    async def _count(self, statement: Any) -> int:
        return int(await self._session.scalar(statement) or 0)


def _tenant_payload(tenant: Tenant) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "code": tenant.code,
        "name": tenant.name,
        "status": tenant.status,
        "settings": dict(tenant.settings),
        "created_at": timestamp(tenant.created_at),
        "updated_at": timestamp(tenant.updated_at),
    }


__all__ = ["TenantService"]
