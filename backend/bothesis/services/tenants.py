"""Tenant profile administration within the authenticated membership boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Tenant
from bothesis.services.audit import AuditService
from bothesis.services import (
    TENANT_MANAGE_PERMISSION,
    AdminNotFoundError,
    AuthContext,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)


class TenantService:
    """Read and update only the actor's durable tenant."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def list_spaces(self, actor: AuthContext) -> dict[str, Any]:
        tenant = await self._tenant(actor)
        return {
            "items": [_tenant_payload(tenant)],
            "total": 1,
            "page": 1,
            "page_size": 1,
        }

    async def get_space(self, actor: AuthContext, tenant_id: UUID) -> dict[str, Any]:
        trusted_tenant_id = require_tenant_permission(actor)
        if tenant_id != trusted_tenant_id:
            raise AdminNotFoundError(f"space not found: {tenant_id}")
        return _tenant_payload(await self._tenant(actor))

    async def update_space(
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
            raise AdminNotFoundError(f"space not found: {tenant_id}")
        tenant = await self._tenant(actor)
        changed: list[str] = []
        if name is not None:
            tenant.name = normalize_required_text(name, "space name", 255)
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
            raise AdminNotFoundError(f"space not found: {tenant_id}")
        return tenant


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
