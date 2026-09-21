"""Read-only tenant and platform dashboard reporting."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import (
    ApprovalRequest,
    Group,
    IntegrationConnection,
    Item,
    Role,
    RoleAssignment,
    Tenant,
    TenantMembership,
    User,
)
from bothesis.services import (
    ACTIVE_STATUS,
    CONNECTION_CONNECTED,
    PLATFORM_TENANT_READ_PERMISSION,
    TENANT_ADMIN_ROLE,
    TENANT_READ_PERMISSION,
    TENANT_SCOPE,
    ControlPlaneNotFoundError,
    AuthContext,
    normalize_page,
    require_platform_permission,
    require_tenant_permission,
    timestamp,
)
from bothesis.services.audit import AuditService
from bothesis.services.identity_access import tenant_payload


class DashboardService:
    """Build permission-scoped administration dashboard read models."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def overview(self, actor: AuthContext) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, TENANT_READ_PERMISSION)
        tenant = await self._tenant(tenant_id)
        metrics = {
            "active_users": await self._count(
                select(func.count())
                .select_from(TenantMembership)
                .join(User, User.id == TenantMembership.user_id)
                .where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.status == ACTIVE_STATUS,
                    TenantMembership.deleted_at.is_(None),
                    User.status.is_(True),
                )
            ),
            # Roles assignable here: the tenant's own, plus the platform's.
            "active_roles": await self._count(
                select(func.count()).select_from(Role).where(
                    Role.scope_type == TENANT_SCOPE,
                    or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
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
                    IntegrationConnection.status == CONNECTION_CONNECTED,
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
            "pending_approval_requests": await self._count(
                select(func.count()).select_from(ApprovalRequest).where(
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.deleted_at.is_(None),
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

    async def platform_overview(self, actor: AuthContext) -> dict[str, Any]:
        """Summarize durable platform state for a root-scoped actor."""

        require_platform_permission(actor, PLATFORM_TENANT_READ_PERMISSION)
        tenants = list(
            await self._session.scalars(
                select(Tenant).order_by(Tenant.created_at, Tenant.id).limit(6)
            )
        )
        health = [await self._workspace_health_payload(tenant) for tenant in tenants]
        return {
            "metrics": {
                "workspaces": await self._count(select(func.count()).select_from(Tenant)),
                "users": await self._count(
                    select(func.count()).select_from(User).where(User.status.is_(True))
                ),
                "connections": await self._count(
                    select(func.count())
                    .select_from(IntegrationConnection)
                    .where(IntegrationConnection.deleted_at.is_(None))
                ),
                "open_reviews": await self._count(
                    select(func.count())
                    .select_from(ApprovalRequest)
                    .where(
                        ApprovalRequest.status == "pending",
                        ApprovalRequest.deleted_at.is_(None),
                    )
                ),
            },
            "workspace_health": health,
        }

    async def list_platform_workspaces(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List the platform workspace health dashboard."""

        require_platform_permission(actor, PLATFORM_TENANT_READ_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        statement = select(Tenant)
        if search and search.strip():
            term = f"%{search.strip()}%"
            statement = statement.where(
                (Tenant.name.ilike(term)) | (Tenant.code.ilike(term))
            )
        if status and status.strip():
            statement = statement.where(Tenant.status == status.strip().casefold())
        total = await self._count(select(func.count()).select_from(statement.subquery()))
        tenants = list(
            await self._session.scalars(
                statement.order_by(Tenant.created_at.desc(), Tenant.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        return {
            "items": [
                await self._workspace_health_payload(tenant) for tenant in tenants
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def _tenant(self, tenant_id: UUID) -> Tenant:
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            raise ControlPlaneNotFoundError(f"tenant not found: {tenant_id}")
        return tenant

    async def _count(self, statement: Any) -> int:
        return int(await self._session.scalar(statement) or 0)

    async def _workspace_health_payload(self, tenant: Tenant) -> dict[str, Any]:
        # The workspace's longest-standing administrator stands in as its owner:
        # ownership is a role assignment now, not a column on the membership.
        owner = await self._session.execute(
            select(User.email, User.display_name)
            .join(RoleAssignment, RoleAssignment.user_id == User.id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .join(
                TenantMembership,
                and_(
                    TenantMembership.user_id == User.id,
                    TenantMembership.tenant_id == tenant.id,
                ),
            )
            .where(
                RoleAssignment.tenant_id == tenant.id,
                RoleAssignment.deleted_at.is_(None),
                Role.code == TENANT_ADMIN_ROLE,
                Role.status == ACTIVE_STATUS,
                TenantMembership.status == ACTIVE_STATUS,
                TenantMembership.deleted_at.is_(None),
            )
            .order_by(User.created_at, User.id)
            .limit(1)
        )
        owner_row = owner.one_or_none()
        return {
            **tenant_payload(tenant),
            "owner": (
                {
                    "display_name": owner_row.display_name,
                    "email": owner_row.email,
                }
                if owner_row is not None
                else None
            ),
            "member_count": await self._count(
                select(func.count())
                .select_from(TenantMembership)
                .where(
                    TenantMembership.tenant_id == tenant.id,
                    TenantMembership.status == ACTIVE_STATUS,
                    TenantMembership.deleted_at.is_(None),
                )
            ),
            "connection_count": await self._count(
                select(func.count())
                .select_from(IntegrationConnection)
                .where(
                    IntegrationConnection.tenant_id == tenant.id,
                    IntegrationConnection.deleted_at.is_(None),
                )
            ),
        }


__all__ = ["DashboardService"]
