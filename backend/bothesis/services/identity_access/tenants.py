"""Tenant profile administration within the authenticated membership boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Tenant
from bothesis.services.audit import AuditService
from bothesis.services import (
    ACTIVE_STATUS,
    PLATFORM_TENANT_READ_PERMISSION,
    TENANT_MANAGE_PERMISSION,
    ControlPlaneNotFoundError,
    AuthContext,
    normalize_required_text,
    require_tenant_permission,
)
from bothesis.services.identity_access import tenant_payload


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
        if actor.has_platform_permissions(PLATFORM_TENANT_READ_PERMISSION):
            tenants = list(
                await self._session.scalars(
                    select(Tenant)
                    .where(Tenant.status == ACTIVE_STATUS)
                    .order_by(Tenant.created_at, Tenant.id)
                )
            )
            return {
                "items": [tenant_payload(tenant) for tenant in tenants],
                "total": len(tenants),
                "page": 1,
                "page_size": len(tenants),
            }
        tenant = await self._tenant(actor)
        return {
            "items": [tenant_payload(tenant)],
            "total": 1,
            "page": 1,
            "page_size": 1,
        }

    async def get_tenant(self, actor: AuthContext, tenant_id: UUID) -> dict[str, Any]:
        trusted_tenant_id = require_tenant_permission(actor)
        if tenant_id != trusted_tenant_id:
            raise ControlPlaneNotFoundError(f"tenant not found: {tenant_id}")
        return tenant_payload(await self._tenant(actor))

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
            raise ControlPlaneNotFoundError(f"tenant not found: {tenant_id}")
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
        return tenant_payload(tenant)

    async def _tenant(self, actor: AuthContext) -> Tenant:
        tenant_id = require_tenant_permission(actor)
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            raise ControlPlaneNotFoundError(f"tenant not found: {tenant_id}")
        return tenant


__all__ = ["TenantService"]
