"""Tenant profile administration within the authenticated membership boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import (
    ApprovalRequest,
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
    normalize_page,
    require_platform_root,
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
        if actor.is_root_admin:
            tenants = list(
                await self._session.scalars(
                    select(Tenant)
                    .where(Tenant.status == ACTIVE_STATUS)
                    .order_by(Tenant.created_at, Tenant.id)
                )
            )
            return {
                "items": [_tenant_payload(tenant) for tenant in tenants],
                "total": len(tenants),
                "page": 1,
                "page_size": len(tenants),
            }
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
                    User.status.is_(True),
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

        require_platform_root(actor)
        tenants = list(
            await self._session.scalars(
                select(Tenant).order_by(Tenant.created_at, Tenant.id).limit(6)
            )
        )
        health = [await self._platform_workspace_payload(tenant) for tenant in tenants]
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
        """List workspace identity and lifecycle facts without impersonation."""

        require_platform_root(actor)
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
                await self._platform_workspace_payload(tenant) for tenant in tenants
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
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

    async def _platform_workspace_payload(self, tenant: Tenant) -> dict[str, Any]:
        owner = await self._session.execute(
            select(User.email, User.display_name)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .join(Role, Role.id == TenantMembership.role_id)
            .where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.status == ACTIVE_STATUS,
                TenantMembership.deleted_at.is_(None),
                Role.code == "owner",
            )
            .order_by(User.created_at, User.id)
            .limit(1)
        )
        owner_row = owner.one_or_none()
        return {
            **_tenant_payload(tenant),
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
