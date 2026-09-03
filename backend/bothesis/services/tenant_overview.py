"""Administration overview built from tenant-scoped durable state."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import (
    AccessRequest,
    Item,
    IntegrationConnection,
    Group,
    Role,
    Tenant,
    TenantMembership,
    User,
)
from bothesis.services.audit import AuditService
from bothesis.services import (
    ACTIVE_STATUS,
    ADMIN_PERMISSION,
    AuthContext,
    require_tenant_permission,
    timestamp,
)


class TenantOverviewService:
    """Aggregate only real control-plane state for the Admin overview."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def overview(self, actor: AuthContext) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ADMIN_PERMISSION)
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            raise RuntimeError("authenticated tenant is unavailable")

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

    async def _count(self, statement: Any) -> int:
        return int(await self._session.scalar(statement) or 0)


__all__ = ["TenantOverviewService"]
