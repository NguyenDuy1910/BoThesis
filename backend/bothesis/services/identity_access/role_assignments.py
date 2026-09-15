"""Grant and revoke roles at platform, tenant, and Collection scope.

This module persists grants and enforces their structural rules — the scope a
role may be used at, and that a principal belongs to the tenant it is granted
in. Whether the actor may make the change is the caller's policy decision, and
stays in the service that owns the operation. Keeping it there is what lets the
creator of a Collection become its owner: the permission that allowed the
create is the permission for the grant, and no first grant has to authorize
itself against a Collection that nobody can reach yet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import (
    Group,
    Item,
    Role,
    RoleAssignment,
    TenantMembership,
    User,
)
from bothesis.services import (
    ACTIVE_STATUS,
    COLLECTION_SCOPE,
    PLATFORM_SCOPE,
    TENANT_SCOPE,
    AdminNotFoundError,
    AdminValidationError,
    timestamp,
)


class RoleAssignmentService:
    """Administer the durable answer to "who holds which role, where"."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Collection scope ---------------------------------------------------

    async def grant_collection_role(
        self,
        item_id: UUID,
        *,
        principal_type: str,
        principal_id: UUID,
        role_code: str,
        created_by_user_id: UUID | None = None,
    ) -> tuple[RoleAssignment, Role]:
        """Give one principal one Collection role, replacing any it holds."""

        tenant_id = await self.collection_tenant_id(item_id)
        principal_type = _principal_type(principal_type)
        role = await self._role(role_code, tenant_id=tenant_id, scope=COLLECTION_SCOPE)
        await self._require_principal(
            tenant_id, principal_type=principal_type, principal_id=principal_id
        )
        # One Collection role per principal: raising a viewer to editor is a
        # change of role, never a second grant that has to be reconciled later.
        await self._retire(
            self._collection_grants(item_id).where(
                _principal_filter(principal_type, principal_id)
            )
        )
        grant = RoleAssignment(
            user_id=principal_id if principal_type == "user" else None,
            group_id=principal_id if principal_type == "group" else None,
            role_id=role.id,
            item_id=item_id,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(grant)
        await self._session.flush()
        return grant, role

    async def revoke_collection_role(
        self,
        item_id: UUID,
        *,
        principal_type: str,
        principal_id: UUID,
    ) -> None:
        await self.collection_tenant_id(item_id)
        principal_type = _principal_type(principal_type)
        retired = await self._retire(
            self._collection_grants(item_id).where(
                _principal_filter(principal_type, principal_id)
            )
        )
        if not retired:
            raise AdminNotFoundError("collection role assignment not found")

    async def list_collection_grants(
        self,
        item_id: UUID,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        await self.collection_tenant_id(item_id)
        if page < 1 or not 1 <= page_size <= 100:
            raise AdminValidationError("invalid collection grant pagination")
        statement = self._collection_grants(item_id)
        total = await self._session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        rows = (
            await self._session.execute(
                select(RoleAssignment, Role)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(
                    RoleAssignment.item_id == item_id,
                    RoleAssignment.deleted_at.is_(None),
                )
                .order_by(
                    RoleAssignment.group_id.is_(None).desc(),
                    RoleAssignment.user_id,
                    RoleAssignment.group_id,
                )
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).all()
        return {
            "items": [self.grant_payload(grant, role) for grant, role in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    # -- Tenant scope -------------------------------------------------------

    async def replace_tenant_roles(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        role_ids: list[UUID],
        created_by_user_id: UUID | None = None,
    ) -> list[Role]:
        """Make the member's tenant roles exactly ``role_ids``.

        The caller authorizes the change; this records it.
        """

        desired = set(role_ids)
        if len(desired) != len(role_ids):
            raise AdminValidationError("role IDs must be unique")
        roles = (
            list(
                await self._session.scalars(
                    select(Role).where(
                        Role.id.in_(desired),
                        Role.scope_type == TENANT_SCOPE,
                        Role.status == ACTIVE_STATUS,
                        or_(Role.tenant_id.is_(None), Role.tenant_id == tenant_id),
                    )
                )
            )
            if desired
            else []
        )
        if {role.id for role in roles} != desired:
            raise AdminNotFoundError("one or more roles were not found")

        held = list(
            await self._session.scalars(
                select(RoleAssignment).where(
                    RoleAssignment.user_id == user_id,
                    RoleAssignment.tenant_id == tenant_id,
                    RoleAssignment.deleted_at.is_(None),
                )
            )
        )
        now = datetime.now(UTC)
        for assignment in held:
            if assignment.role_id not in desired:
                assignment.deleted_at = now
        for role_id in desired - {assignment.role_id for assignment in held}:
            self._session.add(
                RoleAssignment(
                    user_id=user_id,
                    role_id=role_id,
                    tenant_id=tenant_id,
                    created_by_user_id=created_by_user_id,
                )
            )
        await self._session.flush()
        return sorted(roles, key=lambda role: (role.display_name, role.id))

    async def tenant_roles_for_users(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> dict[UUID, list[Role]]:
        """Read the tenant roles held by several members in one query."""

        if not user_ids:
            return {}
        rows = (
            await self._session.execute(
                select(RoleAssignment.user_id, Role)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(
                    RoleAssignment.user_id.in_(user_ids),
                    RoleAssignment.tenant_id == tenant_id,
                    RoleAssignment.deleted_at.is_(None),
                )
                .order_by(Role.display_name, Role.id)
            )
        ).all()
        held: dict[UUID, list[Role]] = {user_id: [] for user_id in user_ids}
        for user_id, role in rows:
            held[user_id].append(role)
        return held

    async def members_holding_role(self, role_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(RoleAssignment)
            .where(
                RoleAssignment.role_id == role_id,
                RoleAssignment.deleted_at.is_(None),
            )
        )
        return int(count or 0)

    # -- Platform scope -----------------------------------------------------

    async def ensure_platform_role(self, user_id: UUID, role_code: str) -> bool:
        """Give a user a platform role once. True when the grant was created.

        Platform administration is a role assignment like any other, so the
        configured bootstrap allowlist creates a row here instead of setting a
        flag on the identity.
        """

        role = await self._role(role_code, tenant_id=None, scope=PLATFORM_SCOPE)
        existing = await self._session.scalar(
            select(RoleAssignment.id).where(
                RoleAssignment.user_id == user_id,
                RoleAssignment.role_id == role.id,
                RoleAssignment.tenant_id.is_(None),
                RoleAssignment.item_id.is_(None),
                RoleAssignment.deleted_at.is_(None),
            )
        )
        if existing is not None:
            return False
        self._session.add(RoleAssignment(user_id=user_id, role_id=role.id))
        await self._session.flush()
        return True

    # -- Shared helpers -----------------------------------------------------

    @staticmethod
    def grant_payload(grant: RoleAssignment, role: Role) -> dict[str, Any]:
        return {
            "item_id": str(grant.item_id) if grant.item_id else None,
            "principal_type": grant.principal_type,
            "principal_id": str(grant.principal_id),
            "role_id": str(role.id),
            "role_code": role.code,
            "role_display_name": role.display_name,
            "created_by_user_id": (
                str(grant.created_by_user_id) if grant.created_by_user_id else None
            ),
            "created_at": timestamp(grant.created_at),
            "updated_at": timestamp(grant.updated_at),
        }

    def _collection_grants(self, item_id: UUID):
        return select(RoleAssignment).where(
            RoleAssignment.item_id == item_id,
            RoleAssignment.deleted_at.is_(None),
        )

    async def _retire(self, statement) -> int:
        grants = list(await self._session.scalars(statement.with_for_update()))
        now = datetime.now(UTC)
        for grant in grants:
            grant.deleted_at = now
        if grants:
            await self._session.flush()
        return len(grants)

    async def collection_tenant_id(self, item_id: UUID) -> UUID:
        """Return the tenant a Collection-scoped grant will be validated against."""

        tenant_id = await self._session.scalar(
            select(Item.tenant_id).where(
                Item.id == item_id,
                Item.item_type == "collection",
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if tenant_id is None:
            raise AdminNotFoundError(f"collection not found: {item_id}")
        return tenant_id

    async def _role(self, role_code: str, *, tenant_id: UUID | None, scope: str) -> Role:
        code = role_code.strip().casefold()
        role = await self._session.scalar(
            select(Role).where(
                Role.code == code,
                Role.scope_type == scope,
                Role.status == ACTIVE_STATUS,
                Role.tenant_id.is_(None)
                if tenant_id is None
                else or_(Role.tenant_id.is_(None), Role.tenant_id == tenant_id),
            )
        )
        if role is None:
            raise AdminNotFoundError(f"role not found: {role_code}")
        return role

    async def _require_principal(
        self, tenant_id: UUID, *, principal_type: str, principal_id: UUID
    ) -> None:
        if principal_type == "group":
            found = await self._session.scalar(
                select(Group.id).where(
                    Group.id == principal_id,
                    Group.tenant_id == tenant_id,
                    Group.status == ACTIVE_STATUS,
                    Group.deleted_at.is_(None),
                )
            )
        else:
            found = await self._session.scalar(
                select(User.id)
                .join(TenantMembership, TenantMembership.user_id == User.id)
                .where(
                    User.id == principal_id,
                    User.status.is_(True),
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.status == ACTIVE_STATUS,
                    TenantMembership.deleted_at.is_(None),
                )
            )
        if found is None:
            raise AdminNotFoundError(f"{principal_type} principal not found")


def _principal_type(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in {"user", "group"}:
        raise AdminValidationError("principal must be user or group")
    return normalized


def _principal_filter(principal_type: str, principal_id: UUID):
    if principal_type == "user":
        return and_(RoleAssignment.user_id == principal_id)
    return and_(RoleAssignment.group_id == principal_id)


__all__ = ["RoleAssignmentService"]
