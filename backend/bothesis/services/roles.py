"""Tenant role and permission administration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Role, TenantMembership
from bothesis.services import (
    ACTIVE_STATUS,
    ADMIN_PERMISSION_CATALOG,
    INACTIVE_STATUS,
    ROLE_MANAGE_PERMISSION,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    AuthService,
    IdentityConflictError,
    normalize_codes,
    normalize_page,
    require_tenant_permission,
    timestamp,
)


class RoleService:
    """Manage the single durable role attached to each tenant membership."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        auth: AuthService | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._auth = auth or AuthService(session)
        self._audit = audit or AuditService(session)

    async def list_permissions(self, actor: AuthContext) -> dict[str, Any]:
        require_tenant_permission(actor, ROLE_MANAGE_PERMISSION)
        return {
            "items": [
                {"code": code, "description": description}
                for code, description in ADMIN_PERMISSION_CATALOG
            ],
            "total": len(ADMIN_PERMISSION_CATALOG),
        }

    async def list_roles(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ROLE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [Role.tenant_id == tenant_id]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(Role.code.ilike(term), Role.display_name.ilike(term))
            )
        if status:
            normalized_status = status.strip().casefold()
            if normalized_status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("role status must be active or inactive")
            filters.append(Role.status == normalized_status)

        member_count = (
            select(func.count(TenantMembership.user_id))
            .where(
                TenantMembership.role_id == Role.id,
                TenantMembership.status == ACTIVE_STATUS,
                TenantMembership.deleted_at.is_(None),
            )
            .correlate(Role)
            .scalar_subquery()
        )
        base = select(Role, member_count.label("member_count")).where(*filters)
        total = await self._session.scalar(
            select(func.count()).select_from(select(Role.id).where(*filters).subquery())
        )
        rows = (
            await self._session.execute(
                base.order_by(Role.display_name, Role.id)
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [_role_payload(role, int(count or 0)) for role, count in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_role(self, actor: AuthContext, role_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ROLE_MANAGE_PERMISSION)
        role = await self._role(tenant_id, role_id)
        member_count = await self._member_count(role.id)
        return _role_payload(role, member_count)

    async def create_role(
        self,
        actor: AuthContext,
        *,
        code: str,
        display_name: str,
        permission_codes: list[str],
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ROLE_MANAGE_PERMISSION)
        permissions = _validated_permissions(permission_codes)
        try:
            role = await self._auth.create_role(
                tenant_id,
                code,
                display_name,
                permission_codes=permissions,
            )
        except IdentityConflictError as exc:
            raise AdminConflictError(str(exc)) from exc
        except ValueError as exc:
            raise AdminValidationError(str(exc)) from exc
        await self._audit.record(
            actor,
            action="role.created",
            resource_type="role",
            resource_id=str(role.id),
            details={"code": role.code, "permission_codes": role.permission_codes},
        )
        return _role_payload(role, 0)

    async def update_role(
        self,
        actor: AuthContext,
        role_id: UUID,
        *,
        display_name: str | None = None,
        permission_codes: list[str] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ROLE_MANAGE_PERMISSION)
        role = await self._role(tenant_id, role_id)
        changed: list[str] = []
        try:
            if display_name is not None:
                role = await self._auth.update_role(
                    tenant_id, role_id, display_name=display_name
                )
                changed.append("display_name")
            if permission_codes is not None:
                role = await self._auth.update_role(
                    tenant_id,
                    role_id,
                    permission_codes=_validated_permissions(permission_codes),
                )
                changed.append("permission_codes")
        except ValueError as exc:
            raise AdminValidationError(str(exc)) from exc
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("role status must be active or inactive")
            if normalized_status == INACTIVE_STATUS:
                if actor.role_id == role_id:
                    raise AdminConflictError(
                        "an administrator cannot disable their own role"
                    )
                if await self._member_count(role_id):
                    raise AdminConflictError(
                        "reassign active members before disabling this role"
                    )
            role.status = normalized_status
            changed.append("status")
        await self._session.flush()
        await self._audit.record(
            actor,
            action="role.updated",
            resource_type="role",
            resource_id=str(role.id),
            details={"changed_fields": changed},
        )
        return _role_payload(role, await self._member_count(role.id))

    async def disable_role(self, actor: AuthContext, role_id: UUID) -> None:
        await self.update_role(actor, role_id, status=INACTIVE_STATUS)

    async def _role(self, tenant_id: UUID, role_id: UUID) -> Role:
        role = await self._session.scalar(
            select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id)
        )
        if role is None:
            raise AdminNotFoundError(f"role not found: {role_id}")
        return role

    async def _member_count(self, role_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(TenantMembership).where(
                TenantMembership.role_id == role_id,
                TenantMembership.status == ACTIVE_STATUS,
                TenantMembership.deleted_at.is_(None),
            )
        )
        return int(count or 0)


def _validated_permissions(values: list[str]) -> list[str]:
    normalized = normalize_codes(values, "permission code")
    known = {code for code, _ in ADMIN_PERMISSION_CATALOG}
    unknown = sorted(set(normalized) - known)
    if unknown:
        raise AdminValidationError(
            "unknown permission codes: " + ", ".join(unknown)
        )
    return normalized


def _role_payload(role: Role, member_count: int) -> dict[str, Any]:
    return {
        "id": str(role.id),
        "tenant_id": str(role.tenant_id),
        "code": role.code,
        "display_name": role.display_name,
        "permission_codes": sorted(role.permission_codes),
        "status": role.status,
        "member_count": member_count,
        "created_at": timestamp(role.created_at),
        "updated_at": timestamp(role.updated_at),
    }


__all__ = ["RoleService"]
