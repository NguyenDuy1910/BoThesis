"""Role and permission administration inside one tenant."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Role, RoleAssignment
from bothesis.services.audit import AuditService
from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services.identity_access.role_assignments import RoleAssignmentService
from bothesis.services import (
    ACTIVE_STATUS,
    INACTIVE_STATUS,
    PERMISSION_CATALOG,
    ROLE_MANAGE_PERMISSION,
    TENANT_SCOPE,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuthContext,
    AuthorizationError,
    IdentityConflictError,
    normalize_page,
    require_tenant_permission,
    timestamp,
)


class RoleService:
    """Manage the tenant roles a member can be assigned."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        auth: IdentityStoreService | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._auth = auth or IdentityStoreService(session)
        self._assignments = RoleAssignmentService(session)
        self._audit = audit or AuditService(session)

    async def list_permissions(self, actor: AuthContext) -> dict[str, Any]:
        """Return the permissions a tenant role may carry."""

        require_tenant_permission(actor, ROLE_MANAGE_PERMISSION)
        assignable = [
            permission
            for permission in PERMISSION_CATALOG
            if TENANT_SCOPE in permission.scopes
            and permission.code in actor.permission_codes
        ]
        return {
            "items": [
                {
                    "code": permission.code,
                    "description": permission.description,
                    "scopes": sorted(permission.scopes),
                }
                for permission in assignable
            ],
            "total": len(assignable),
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
        filters = [
            Role.scope_type == TENANT_SCOPE,
            or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
        ]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(or_(Role.code.ilike(term), Role.display_name.ilike(term)))
        if status:
            normalized_status = status.strip().casefold()
            if normalized_status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("role status must be active or inactive")
            filters.append(Role.status == normalized_status)

        member_count = (
            select(func.count(RoleAssignment.id))
            .where(
                RoleAssignment.role_id == Role.id,
                RoleAssignment.tenant_id == tenant_id,
                RoleAssignment.deleted_at.is_(None),
            )
            .correlate(Role)
            .scalar_subquery()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(select(Role.id).where(*filters).subquery())
        )
        rows = (
            await self._session.execute(
                select(Role, member_count.label("member_count"))
                .where(*filters)
                .order_by(Role.display_name, Role.id)
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        permissions = await self._auth.permissions_for_roles(
            [role.id for role, _ in rows]
        )
        return {
            "items": [
                _role_payload(role, permissions.get(role.id, ()), int(count or 0))
                for role, count in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_role(self, actor: AuthContext, role_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ROLE_MANAGE_PERMISSION)
        role = await self._role(tenant_id, role_id)
        return _role_payload(
            role,
            await self._auth.role_permissions(role.id),
            await self._member_count(tenant_id, role.id),
        )

    async def create_role(
        self,
        actor: AuthContext,
        *,
        code: str,
        display_name: str,
        permission_codes: list[str],
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ROLE_MANAGE_PERMISSION)
        self._require_permission_ceiling(actor, permission_codes)
        try:
            role = await self._auth.create_role(
                tenant_id,
                code,
                display_name,
                permission_codes=permission_codes,
            )
        except IdentityConflictError as exc:
            raise AdminConflictError(str(exc)) from exc
        except ValueError as exc:
            raise AdminValidationError(str(exc)) from exc
        granted = await self._auth.role_permissions(role.id)
        await self._audit.record(
            actor,
            action="role.created",
            resource_type="role",
            resource_id=str(role.id),
            details={"code": role.code, "permission_codes": list(granted)},
        )
        return _role_payload(role, granted, 0)

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
        if role.is_system:
            raise AdminValidationError("a platform-defined role cannot be changed")
        if permission_codes is not None and role.code in actor.role_codes:
            raise AdminConflictError(
                "an administrator cannot change permissions of a role they hold"
            )
        if permission_codes is not None:
            self._require_permission_ceiling(actor, permission_codes)
        changed: list[str] = []
        before_permissions = await self._auth.role_permissions(role.id)
        try:
            if display_name is not None:
                role = await self._auth.update_role(
                    tenant_id, role_id, display_name=display_name
                )
                changed.append("display_name")
            if permission_codes is not None:
                role = await self._auth.update_role(
                    tenant_id, role_id, permission_codes=permission_codes
                )
                changed.append("permission_codes")
        except AuthorizationError as exc:
            raise AdminValidationError(str(exc)) from exc
        except ValueError as exc:
            raise AdminValidationError(str(exc)) from exc
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("role status must be active or inactive")
            if normalized_status == INACTIVE_STATUS:
                if role.code in actor.role_codes:
                    raise AdminConflictError(
                        "an administrator cannot disable a role they hold"
                    )
                if await self._member_count(tenant_id, role_id):
                    raise AdminConflictError(
                        "reassign active members before disabling this role"
                    )
            role.status = normalized_status
            changed.append("status")
        await self._session.flush()
        current_permissions = await self._auth.role_permissions(role.id)
        details: dict[str, Any] = {"changed_fields": changed}
        if permission_codes is not None:
            details["permission_codes"] = {
                "before": list(before_permissions),
                "after": list(current_permissions),
            }
        await self._audit.record(
            actor,
            action="role.updated",
            resource_type="role",
            resource_id=str(role.id),
            details=details,
        )
        return _role_payload(
            role,
            current_permissions,
            await self._member_count(tenant_id, role.id),
        )

    async def disable_role(self, actor: AuthContext, role_id: UUID) -> None:
        await self.update_role(actor, role_id, status=INACTIVE_STATUS)

    async def _role(self, tenant_id: UUID, role_id: UUID) -> Role:
        role = await self._session.scalar(
            select(Role).where(
                Role.id == role_id,
                Role.scope_type == TENANT_SCOPE,
                or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
            )
        )
        if role is None:
            raise AdminNotFoundError(f"role not found: {role_id}")
        return role

    async def _member_count(self, tenant_id: UUID, role_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(RoleAssignment)
            .where(
                RoleAssignment.role_id == role_id,
                RoleAssignment.tenant_id == tenant_id,
                RoleAssignment.deleted_at.is_(None),
            )
        )
        return int(count or 0)

    @staticmethod
    def _require_permission_ceiling(
        actor: AuthContext, permission_codes: list[str]
    ) -> None:
        disallowed = sorted(set(permission_codes) - set(actor.permission_codes))
        if disallowed:
            raise AdminValidationError(
                "roles may include only permissions already held by the acting "
                f"administrator: {', '.join(disallowed)}"
            )


def _role_payload(
    role: Role, permission_codes: tuple[str, ...], member_count: int
) -> dict[str, Any]:
    return {
        "id": str(role.id),
        "tenant_id": str(role.tenant_id) if role.tenant_id else None,
        "code": role.code,
        "display_name": role.display_name,
        "scope_type": role.scope_type,
        "is_system": role.is_system,
        "permission_codes": sorted(permission_codes),
        "status": role.status,
        "member_count": member_count,
        "created_at": timestamp(role.created_at),
        "updated_at": timestamp(role.updated_at),
    }


__all__ = ["RoleService"]
