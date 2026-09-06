"""Tenant-scoped user and membership administration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Group, GroupMembership, Role, TenantMembership, User
from bothesis.services.audit import AuditService
from bothesis.services.identity_store import IdentityStoreService
from bothesis.services import (
    ACTIVE_STATUS,
    INACTIVE_STATUS,
    USER_MANAGE_PERMISSION,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuthContext,
    IdentityConflictError,
    normalize_page,
    require_tenant_permission,
    timestamp,
)


class UserService:
    """Manage durable users without trusting frontend tenant claims."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        auth: IdentityStoreService | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._auth = auth or IdentityStoreService(session)
        self._audit = audit or AuditService(session)

    async def list_users(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
        role_id: UUID | None = None,
        sort: str = "name",
        direction: str = "asc",
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, USER_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.deleted_at.is_(None),
        ]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(User.email.ilike(term), User.display_name.ilike(term))
            )
        if status:
            normalized_status = status.strip().casefold()
            if normalized_status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("user status must be active or inactive")
            filters.append(User.status == normalized_status)
        if role_id is not None:
            filters.append(TenantMembership.role_id == role_id)

        base = (
            select(User, TenantMembership, Role)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .join(Role, Role.id == TenantMembership.role_id)
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        sort_columns = {
            "created_at": User.created_at,
            "email": User.email,
            "last_login_at": User.last_login_at,
            "name": func.coalesce(User.display_name, User.email),
            "status": User.status,
        }
        sort_column = sort_columns.get(sort)
        if sort_column is None:
            raise AdminValidationError("unsupported user sort field")
        if direction not in {"asc", "desc"}:
            raise AdminValidationError("sort direction must be asc or desc")
        order = sort_column.desc() if direction == "desc" else sort_column.asc()
        rows = (
            await self._session.execute(
                base.order_by(order, User.id).limit(page_size).offset(offset)
            )
        ).all()
        groups_by_user = await self._groups_for_users(
            tenant_id, [user.id for user, _, _ in rows]
        )
        return {
            "items": [
                _user_payload(user, membership, role, groups_by_user.get(user.id, []))
                for user, membership, role in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_user(self, actor: AuthContext, user_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, USER_MANAGE_PERMISSION)
        user, membership, role = await self._membership_row(tenant_id, user_id)
        groups = (await self._groups_for_users(tenant_id, [user_id])).get(user_id, [])
        return _user_payload(user, membership, role, groups)

    async def create_user(
        self,
        actor: AuthContext,
        *,
        email: str,
        display_name: str | None,
        role_id: UUID,
        group_ids: list[UUID] | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, USER_MANAGE_PERMISSION)
        await self._role(tenant_id, role_id)
        try:
            user = await self._auth.create_user(email, display_name=display_name)
        except IdentityConflictError as exc:
            raise AdminConflictError(str(exc)) from exc
        except ValueError as exc:
            raise AdminValidationError(str(exc)) from exc
        membership = await self._auth.assign_membership(user.id, tenant_id, role_id)
        groups = await self._replace_groups(
            tenant_id, user.id, group_ids or []
        )
        role = await self._role(tenant_id, role_id)
        await self._audit.record(
            actor,
            action="user.created",
            resource_type="user",
            resource_id=str(user.id),
            details={"email": user.email, "role_id": str(role_id)},
        )
        return _user_payload(user, membership, role, groups)

    async def update_user(
        self,
        actor: AuthContext,
        user_id: UUID,
        *,
        display_name: str | None = None,
        role_id: UUID | None = None,
        status: str | None = None,
        group_ids: list[UUID] | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, USER_MANAGE_PERMISSION)
        user, membership, role = await self._membership_row(tenant_id, user_id)
        changed: list[str] = []
        if display_name is not None:
            try:
                user = await self._auth.update_user(
                    user_id, display_name=display_name
                )
            except ValueError as exc:
                raise AdminValidationError(str(exc)) from exc
            changed.append("display_name")
        if role_id is not None and role_id != membership.role_id:
            role = await self._role(tenant_id, role_id)
            membership.role_id = role.id
            changed.append("role_id")
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("user status must be active or inactive")
            if user_id == actor.user_id and normalized_status != ACTIVE_STATUS:
                raise AdminConflictError("an administrator cannot disable their own user")
            user.status = normalized_status
            membership.status = normalized_status
            if normalized_status == ACTIVE_STATUS:
                membership.deleted_at = None
            changed.append("status")
        groups = (
            await self._replace_groups(tenant_id, user_id, group_ids)
            if group_ids is not None
            else (await self._groups_for_users(tenant_id, [user_id])).get(user_id, [])
        )
        if group_ids is not None:
            changed.append("groups")
        await self._session.flush()
        await self._audit.record(
            actor,
            action="user.updated",
            resource_type="user",
            resource_id=str(user.id),
            details={"changed_fields": changed},
        )
        return _user_payload(user, membership, role, groups)

    async def _membership_row(
        self, tenant_id: UUID, user_id: UUID
    ) -> tuple[User, TenantMembership, Role]:
        row = (
            await self._session.execute(
                select(User, TenantMembership, Role)
                .join(TenantMembership, TenantMembership.user_id == User.id)
                .join(Role, Role.id == TenantMembership.role_id)
                .where(
                    User.id == user_id,
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise AdminNotFoundError(f"user not found: {user_id}")
        return row

    async def _role(self, tenant_id: UUID, role_id: UUID) -> Role:
        role = await self._session.scalar(
            select(Role).where(
                Role.id == role_id,
                Role.tenant_id == tenant_id,
                Role.status == ACTIVE_STATUS,
            )
        )
        if role is None:
            raise AdminNotFoundError(f"role not found: {role_id}")
        return role

    async def _groups_for_users(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> dict[UUID, list[Group]]:
        if not user_ids:
            return {}
        rows = (
            await self._session.execute(
                select(GroupMembership.user_id, Group)
                .join(Group, Group.id == GroupMembership.group_id)
                .where(
                    GroupMembership.user_id.in_(user_ids),
                    GroupMembership.status == ACTIVE_STATUS,
                    GroupMembership.deleted_at.is_(None),
                    Group.tenant_id == tenant_id,
                    Group.status == ACTIVE_STATUS,
                    Group.deleted_at.is_(None),
                )
                .order_by(Group.display_name, Group.id)
            )
        ).all()
        result: dict[UUID, list[Group]] = {}
        for user_id, group in rows:
            result.setdefault(user_id, []).append(group)
        return result

    async def _replace_groups(
        self, tenant_id: UUID, user_id: UUID, group_ids: list[UUID]
    ) -> list[Group]:
        desired_ids = set(group_ids)
        if len(desired_ids) != len(group_ids):
            raise AdminValidationError("group IDs must be unique")
        groups = list(
            await self._session.scalars(
                select(Group).where(
                    Group.id.in_(desired_ids),
                    Group.tenant_id == tenant_id,
                    Group.status == ACTIVE_STATUS,
                    Group.deleted_at.is_(None),
                )
            )
        ) if desired_ids else []
        if {group.id for group in groups} != desired_ids:
            raise AdminNotFoundError("one or more groups were not found")

        existing = list(
            await self._session.scalars(
                select(GroupMembership)
                .join(Group, Group.id == GroupMembership.group_id)
                .where(
                    GroupMembership.user_id == user_id,
                    Group.tenant_id == tenant_id,
                )
                .with_for_update()
            )
        )
        now = datetime.now(UTC)
        by_group = {membership.group_id: membership for membership in existing}
        for membership in existing:
            if membership.group_id not in desired_ids:
                membership.status = INACTIVE_STATUS
                membership.deleted_at = now
        for group_id in desired_ids:
            membership = by_group.get(group_id)
            if membership is None:
                self._session.add(
                    GroupMembership(
                        group_id=group_id,
                        user_id=user_id,
                        joined_at=now,
                    )
                )
            else:
                membership.status = ACTIVE_STATUS
                membership.joined_at = membership.joined_at or now
                membership.deleted_at = None
        await self._session.flush()
        return sorted(groups, key=lambda group: (group.display_name, group.id))


def _user_payload(
    user: User,
    membership: TenantMembership,
    role: Role,
    groups: list[Group],
) -> dict[str, Any]:
    permissions = sorted(set(role.permission_codes))
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "last_login_at": timestamp(user.last_login_at),
        "created_at": timestamp(user.created_at),
        "updated_at": timestamp(user.updated_at),
        "membership": {
            "status": membership.status,
            "joined_at": timestamp(membership.joined_at),
            "role": {
                "id": str(role.id),
                "code": role.code,
                "display_name": role.display_name,
            },
        },
        "groups": [
            {
                "id": str(group.id),
                "code": group.code,
                "display_name": group.display_name,
            }
            for group in groups
        ],
        "permission_codes": permissions,
    }


__all__ = ["UserService"]
