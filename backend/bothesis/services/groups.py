"""Tenant group and membership administration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Group, GroupMembership, TenantMembership, User
from bothesis.services import (
    ACTIVE_STATUS,
    GROUP_MANAGE_PERMISSION,
    INACTIVE_STATUS,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    normalize_code,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)


class GroupService:
    """Manage groups that may receive Collection access grants."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def list_groups(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, GROUP_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [Group.tenant_id == tenant_id, Group.deleted_at.is_(None)]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(Group.code.ilike(term), Group.display_name.ilike(term))
            )
        if status:
            normalized_status = status.strip().casefold()
            if normalized_status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("group status must be active or inactive")
            filters.append(Group.status == normalized_status)

        member_count = (
            select(func.count(GroupMembership.user_id))
            .where(
                GroupMembership.group_id == Group.id,
                GroupMembership.status == ACTIVE_STATUS,
                GroupMembership.deleted_at.is_(None),
            )
            .correlate(Group)
            .scalar_subquery()
        )
        total = await self._session.scalar(
            select(func.count()).select_from(select(Group.id).where(*filters).subquery())
        )
        rows = (
            await self._session.execute(
                select(Group, member_count.label("member_count"))
                .where(*filters)
                .order_by(Group.display_name, Group.id)
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [_group_payload(group, int(count or 0)) for group, count in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_group(self, actor: AuthContext, group_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, GROUP_MANAGE_PERMISSION)
        group = await self._group(tenant_id, group_id)
        payload = _group_payload(group, await self._member_count(group.id))
        payload["members"] = await self._member_payloads(group.id)
        return payload

    async def create_group(
        self,
        actor: AuthContext,
        *,
        code: str,
        display_name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, GROUP_MANAGE_PERMISSION)
        normalized_code = normalize_code(code, "group code")
        if await self._session.scalar(
            select(Group.id).where(
                Group.tenant_id == tenant_id, Group.code == normalized_code
            )
        ) is not None:
            raise AdminConflictError(
                f"group code already exists in tenant: {normalized_code}"
            )
        group = Group(
            tenant_id=tenant_id,
            code=normalized_code,
            display_name=normalize_required_text(
                display_name, "group display name", 255
            ),
            description=(
                normalize_required_text(description, "group description", 2_000)
                if description is not None
                else None
            ),
        )
        self._session.add(group)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="group.created",
            resource_type="group",
            resource_id=str(group.id),
            details={"code": group.code},
        )
        return _group_payload(group, 0)

    async def update_group(
        self,
        actor: AuthContext,
        group_id: UUID,
        *,
        display_name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, GROUP_MANAGE_PERMISSION)
        group = await self._group(tenant_id, group_id)
        changed: list[str] = []
        if display_name is not None:
            group.display_name = normalize_required_text(
                display_name, "group display name", 255
            )
            changed.append("display_name")
        if description is not None:
            group.description = normalize_required_text(
                description, "group description", 2_000
            )
            changed.append("description")
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("group status must be active or inactive")
            group.status = normalized_status
            changed.append("status")
        await self._session.flush()
        await self._audit.record(
            actor,
            action="group.updated",
            resource_type="group",
            resource_id=str(group.id),
            details={"changed_fields": changed},
        )
        return _group_payload(group, await self._member_count(group.id))

    async def replace_members(
        self,
        actor: AuthContext,
        group_id: UUID,
        user_ids: list[UUID],
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, GROUP_MANAGE_PERMISSION)
        group = await self._group(tenant_id, group_id)
        desired_ids = set(user_ids)
        if len(desired_ids) != len(user_ids):
            raise AdminValidationError("user IDs must be unique")
        valid_ids = set(
            await self._session.scalars(
                select(TenantMembership.user_id).where(
                    TenantMembership.user_id.in_(desired_ids),
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.status == ACTIVE_STATUS,
                    TenantMembership.deleted_at.is_(None),
                )
            )
        ) if desired_ids else set()
        if valid_ids != desired_ids:
            raise AdminNotFoundError("one or more users were not found")

        existing = list(
            await self._session.scalars(
                select(GroupMembership)
                .where(GroupMembership.group_id == group.id)
                .with_for_update()
            )
        )
        by_user = {membership.user_id: membership for membership in existing}
        now = datetime.now(UTC)
        for membership in existing:
            if membership.user_id not in desired_ids:
                membership.status = INACTIVE_STATUS
                membership.deleted_at = now
        for user_id in desired_ids:
            membership = by_user.get(user_id)
            if membership is None:
                self._session.add(
                    GroupMembership(
                        group_id=group.id,
                        user_id=user_id,
                        joined_at=now,
                    )
                )
            else:
                membership.status = ACTIVE_STATUS
                membership.joined_at = membership.joined_at or now
                membership.deleted_at = None
        await self._session.flush()
        await self._audit.record(
            actor,
            action="group.members_replaced",
            resource_type="group",
            resource_id=str(group.id),
            details={"member_count": len(desired_ids)},
        )
        payload = _group_payload(group, len(desired_ids))
        payload["members"] = await self._member_payloads(group.id)
        return payload

    async def delete_group(self, actor: AuthContext, group_id: UUID) -> None:
        tenant_id = require_tenant_permission(actor, GROUP_MANAGE_PERMISSION)
        group = await self._group(tenant_id, group_id)
        now = datetime.now(UTC)
        group.status = INACTIVE_STATUS
        group.deleted_at = now
        memberships = list(
            await self._session.scalars(
                select(GroupMembership).where(
                    GroupMembership.group_id == group.id,
                    GroupMembership.deleted_at.is_(None),
                )
            )
        )
        for membership in memberships:
            membership.status = INACTIVE_STATUS
            membership.deleted_at = now
        await self._session.flush()
        await self._audit.record(
            actor,
            action="group.deleted",
            resource_type="group",
            resource_id=str(group.id),
        )

    async def _group(self, tenant_id: UUID, group_id: UUID) -> Group:
        group = await self._session.scalar(
            select(Group).where(
                Group.id == group_id,
                Group.tenant_id == tenant_id,
                Group.deleted_at.is_(None),
            )
        )
        if group is None:
            raise AdminNotFoundError(f"group not found: {group_id}")
        return group

    async def _member_count(self, group_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(GroupMembership).where(
                GroupMembership.group_id == group_id,
                GroupMembership.status == ACTIVE_STATUS,
                GroupMembership.deleted_at.is_(None),
            )
        )
        return int(count or 0)

    async def _member_payloads(self, group_id: UUID) -> list[dict[str, Any]]:
        rows = (
            await self._session.execute(
                select(User, GroupMembership)
                .join(GroupMembership, GroupMembership.user_id == User.id)
                .where(
                    GroupMembership.group_id == group_id,
                    GroupMembership.status == ACTIVE_STATUS,
                    GroupMembership.deleted_at.is_(None),
                )
                .order_by(func.coalesce(User.display_name, User.email), User.id)
            )
        ).all()
        return [
            {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "joined_at": timestamp(membership.joined_at),
            }
            for user, membership in rows
        ]


def _group_payload(group: Group, member_count: int) -> dict[str, Any]:
    return {
        "id": str(group.id),
        "tenant_id": str(group.tenant_id),
        "code": group.code,
        "display_name": group.display_name,
        "description": group.description,
        "status": group.status,
        "member_count": member_count,
        "created_at": timestamp(group.created_at),
        "updated_at": timestamp(group.updated_at),
    }


__all__ = ["GroupService"]
