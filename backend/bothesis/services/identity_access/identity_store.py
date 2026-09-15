"""Database-backed identity and authorization services.

Authentication credentials and refresh-token sessions are intentionally not
implemented here because the current database design does not contain those
records. This module resolves durable users, tenant membership, roles,
permissions, and active group membership.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.engine import SessionFactory
from bothesis.db.models import (
    Group,
    GroupMembership,
    Item,
    Permission,
    Role,
    RoleAssignment,
    RolePermission,
    Tenant,
    TenantMembership,
    User,
)
from bothesis.services import (
    ACTIVE_STATUS,
    PERMISSIONS_BY_CODE,
    PERMISSION_CATALOG,
    PLATFORM_SCOPE,
    SYSTEM_ROLES,
    TENANT_SCOPE,
    AuthContext,
    AuthorizationError,
    IdentityConflictError,
    IdentityInactiveError,
    IdentityNotFoundError,
    INACTIVE_STATUS,
    TenantMembershipSummary,
)


class IdentityStoreService:
    """Manage durable identities and resolve fail-closed authorization context."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(
        self,
        email: str,
        *,
        display_name: str | None = None,
        preferences: Mapping[str, Any] | None = None,
    ) -> User:
        normalized_email = _normalize_email(email)
        existing = await self._session.scalar(
            select(User.id).where(User.email == normalized_email)
        )
        if existing is not None:
            raise IdentityConflictError(
                f"user email already exists: {normalized_email}"
            )

        user = User(
            email=normalized_email,
            display_name=_optional_text(display_name, "display name", 255),
            preferences=dict(preferences or {}),
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_user(self, user_id: UUID, *, include_inactive: bool = False) -> User:
        user = await self._session.get(User, user_id)
        if user is None or (not include_inactive and not user.status):
            raise IdentityNotFoundError(f"user not found: {user_id}")
        return user

    async def get_user_by_email(
        self,
        email: str,
        *,
        include_inactive: bool = False,
    ) -> User:
        user = await self._session.scalar(
            select(User).where(User.email == _normalize_email(email))
        )
        if user is None or (not include_inactive and not user.status):
            raise IdentityNotFoundError("user not found")
        return user

    async def update_user(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        preferences: Mapping[str, Any] | None = None,
    ) -> User:
        user = await self.get_user(user_id, include_inactive=True)
        if display_name is not None:
            user.display_name = _optional_text(display_name, "display name", 255)
        if preferences is not None:
            user.preferences = dict(preferences)
        await self._session.flush()
        return user

    async def set_user_status(self, user_id: UUID, status: bool) -> User:
        user = await self.get_user(user_id, include_inactive=True)
        user.status = status
        await self._session.flush()
        return user

    async def create_tenant(
        self,
        code: str,
        name: str,
        *,
        settings: Mapping[str, Any] | None = None,
    ) -> Tenant:
        normalized_code = _normalize_code(code, "tenant code")
        existing = await self._session.scalar(
            select(Tenant.id).where(Tenant.code == normalized_code)
        )
        if existing is not None:
            raise IdentityConflictError(
                f"tenant code already exists: {normalized_code}"
            )

        tenant = Tenant(
            code=normalized_code,
            name=_required_text(name, "tenant name", 255),
            settings=dict(settings or {}),
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def get_tenant(
        self,
        tenant_id: UUID,
        *,
        include_inactive: bool = False,
    ) -> Tenant:
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None or (not include_inactive and tenant.status != ACTIVE_STATUS):
            raise IdentityNotFoundError(f"tenant not found: {tenant_id}")
        return tenant

    async def update_tenant(
        self,
        tenant_id: UUID,
        *,
        name: str | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> Tenant:
        tenant = await self.get_tenant(tenant_id, include_inactive=True)
        if name is not None:
            tenant.name = _required_text(name, "tenant name", 255)
        if settings is not None:
            tenant.settings = dict(settings)
        await self._session.flush()
        return tenant

    async def set_tenant_status(self, tenant_id: UUID, status: str) -> Tenant:
        tenant = await self.get_tenant(tenant_id, include_inactive=True)
        tenant.status = _required_text(status, "tenant status", 16).casefold()
        await self._session.flush()
        return tenant

    async def sync_system_roles(self) -> None:
        """Make the database match the permission and system-role catalogs.

        Permissions and platform-defined roles are product definitions, not
        tenant data, so they are declared in code and reconciled here. Running
        this again is safe, and is how a new capability reaches deployed roles.
        """

        for permission in PERMISSION_CATALOG:
            await self._session.execute(
                insert(Permission)
                .values(
                    code=permission.code,
                    description=permission.description,
                    scope_types=sorted(permission.scopes),
                )
                .on_conflict_do_update(
                    index_elements=[Permission.code],
                    set_={
                        "description": permission.description,
                        "scope_types": sorted(permission.scopes),
                    },
                )
            )
        for definition in SYSTEM_ROLES:
            role_id = await self._session.scalar(
                insert(Role)
                .values(
                    tenant_id=None,
                    code=definition.code,
                    display_name=definition.display_name,
                    scope_type=definition.scope_type,
                    is_system=True,
                    status=ACTIVE_STATUS,
                )
                .on_conflict_do_update(
                    index_elements=[Role.tenant_id, Role.code],
                    set_={
                        "display_name": definition.display_name,
                        "scope_type": definition.scope_type,
                        "status": ACTIVE_STATUS,
                        "updated_at": datetime.now(UTC),
                    },
                )
                .returning(Role.id)
            )
            await self._replace_role_permissions(role_id, definition.permission_codes)
        await self._session.flush()

    async def create_role(
        self,
        tenant_id: UUID,
        code: str,
        display_name: str,
        *,
        permission_codes: Iterable[str] = (),
    ) -> Role:
        """Define a tenant-owned role. Platform and Collection roles are system roles."""

        await self.get_tenant(tenant_id)
        normalized_code = _normalize_code(code, "role code")
        conflict = await self._session.scalar(
            select(Role.id).where(
                or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
                Role.code == normalized_code,
            )
        )
        if conflict is not None:
            raise IdentityConflictError(
                f"role code is already in use: {normalized_code}"
            )

        role = Role(
            tenant_id=tenant_id,
            code=normalized_code,
            display_name=_required_text(display_name, "role display name", 255),
            scope_type=TENANT_SCOPE,
            is_system=False,
        )
        self._session.add(role)
        await self._session.flush()
        await self._replace_role_permissions(
            role.id, _tenant_permissions(permission_codes)
        )
        await self._session.flush()
        return role

    async def get_role(
        self,
        tenant_id: UUID,
        role_id: UUID,
        *,
        include_inactive: bool = False,
    ) -> Role:
        statement = select(Role).where(
            Role.id == role_id,
            or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
        )
        if not include_inactive:
            statement = statement.where(Role.status == ACTIVE_STATUS)
        role = await self._session.scalar(statement)
        if role is None:
            raise IdentityNotFoundError(f"role not found: {role_id}")
        return role

    async def list_roles(
        self,
        tenant_id: UUID,
        *,
        include_inactive: bool = False,
    ) -> list[Role]:
        """Return the roles assignable inside one tenant, system roles included."""

        await self.get_tenant(tenant_id, include_inactive=include_inactive)
        statement = select(Role).where(
            Role.scope_type == TENANT_SCOPE,
            or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
        )
        if not include_inactive:
            statement = statement.where(Role.status == ACTIVE_STATUS)
        result = await self._session.scalars(statement.order_by(Role.code))
        return list(result)

    async def role_permissions(self, role_id: UUID) -> tuple[str, ...]:
        codes = await self._session.scalars(
            select(RolePermission.permission_code)
            .where(RolePermission.role_id == role_id, RolePermission.deleted_at.is_(None))
            .order_by(RolePermission.permission_code)
        )
        return tuple(codes)

    async def permissions_for_roles(
        self, role_ids: Iterable[UUID]
    ) -> dict[UUID, tuple[str, ...]]:
        """Read several roles' permissions in one query, for list endpoints."""

        wanted = list(role_ids)
        if not wanted:
            return {}
        rows = (
            await self._session.execute(
                select(RolePermission.role_id, RolePermission.permission_code)
                .where(
                    RolePermission.role_id.in_(wanted),
                    RolePermission.deleted_at.is_(None),
                )
                .order_by(RolePermission.permission_code)
            )
        ).all()
        held: dict[UUID, list[str]] = {role_id: [] for role_id in wanted}
        for role_id, code in rows:
            held[role_id].append(code)
        return {role_id: tuple(codes) for role_id, codes in held.items()}

    async def update_role(
        self,
        tenant_id: UUID,
        role_id: UUID,
        *,
        display_name: str | None = None,
        permission_codes: Iterable[str] | None = None,
    ) -> Role:
        role = await self.get_role(tenant_id, role_id, include_inactive=True)
        if role.is_system:
            raise AuthorizationError("a platform-defined role cannot be edited")
        if display_name is not None:
            role.display_name = _required_text(display_name, "role display name", 255)
        if permission_codes is not None:
            await self._replace_role_permissions(
                role.id, _tenant_permissions(permission_codes)
            )
        await self._session.flush()
        return role

    async def set_role_status(
        self,
        tenant_id: UUID,
        role_id: UUID,
        status: str,
    ) -> Role:
        role = await self.get_role(tenant_id, role_id, include_inactive=True)
        if role.is_system:
            raise AuthorizationError("a platform-defined role cannot be disabled")
        role.status = _required_text(status, "role status", 16).casefold()
        await self._session.flush()
        return role

    async def _replace_role_permissions(
        self, role_id: UUID, permission_codes: Iterable[str]
    ) -> None:
        """Make the role carry exactly these permissions, tombstoning the rest."""

        wanted = set(permission_codes)
        held = list(
            await self._session.scalars(
                select(RolePermission).where(RolePermission.role_id == role_id)
            )
        )
        now = datetime.now(UTC)
        for grant in held:
            if grant.permission_code in wanted:
                grant.deleted_at = None
            elif grant.deleted_at is None:
                grant.deleted_at = now
        for code in wanted - {grant.permission_code for grant in held}:
            self._session.add(RolePermission(role_id=role_id, permission_code=code))
        await self._session.flush()

    async def assign_membership(
        self,
        user_id: UUID,
        tenant_id: UUID,
    ) -> TenantMembership:
        """Record that a user belongs to a tenant. Roles are assigned separately."""

        await self.get_user(user_id)
        await self.get_tenant(tenant_id)

        membership = await self._session.get(
            TenantMembership, {"user_id": user_id, "tenant_id": tenant_id}
        )
        if membership is None:
            membership = TenantMembership(
                user_id=user_id,
                tenant_id=tenant_id,
                joined_at=datetime.now(UTC),
            )
            self._session.add(membership)
        else:
            membership.status = ACTIVE_STATUS
            membership.joined_at = membership.joined_at or datetime.now(UTC)
            membership.deleted_at = None
        await self._session.flush()
        return membership

    async def remove_membership(
        self, user_id: UUID, tenant_id: UUID | None = None
    ) -> None:
        membership = await self._membership(user_id, tenant_id)
        if membership is None:
            raise IdentityNotFoundError(f"membership not found for user: {user_id}")
        if membership.deleted_at is not None:
            return
        now = datetime.now(UTC)
        membership.status = INACTIVE_STATUS
        membership.deleted_at = now
        # Losing membership loses every role held inside that tenant, so a
        # readmitted member never silently regains yesterday's access.
        tenant_collections = select(Item.id).where(
            Item.tenant_id == membership.tenant_id
        )
        assignments = await self._session.scalars(
            select(RoleAssignment).where(
                RoleAssignment.user_id == user_id,
                RoleAssignment.deleted_at.is_(None),
                or_(
                    RoleAssignment.tenant_id == membership.tenant_id,
                    RoleAssignment.item_id.in_(tenant_collections),
                ),
            )
        )
        for assignment in assignments:
            assignment.deleted_at = now
        await self._session.flush()

    async def get_context(
        self, user_id: UUID, *, tenant_id: UUID | None = None
    ) -> AuthContext:
        """Resolve what the caller may do, fail-closed, from durable grants only."""

        user = await self._session.get(User, user_id)
        if user is None:
            raise IdentityNotFoundError(f"user not found: {user_id}")
        if not user.status:
            raise IdentityInactiveError(f"user is not active: {user_id}")

        memberships = list(
            await self._session.scalars(
                select(TenantMembership).where(
                    TenantMembership.user_id == user_id,
                    TenantMembership.deleted_at.is_(None),
                    *(
                        (TenantMembership.tenant_id == tenant_id,)
                        if tenant_id is not None
                        else ()
                    ),
                )
            )
        )
        if tenant_id is None and len(memberships) > 1:
            raise AuthorizationError("tenant ID is required for a multi-tenant user")
        membership = memberships[0] if memberships else None
        if membership is None:
            if tenant_id is not None:
                raise AuthorizationError("user is not a member of the requested tenant")
            _, platform_permissions = await self._grants(user_id, None, ())
            return AuthContext(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                tenant_id=None,
                permission_codes=(),
                group_ids=(),
                role_codes=(),
                platform_permissions=platform_permissions,
            )

        if membership.status != ACTIVE_STATUS:
            raise IdentityInactiveError(f"membership is not active: {user_id}")
        tenant = await self.get_tenant(membership.tenant_id, include_inactive=True)
        if tenant.status != ACTIVE_STATUS:
            raise IdentityInactiveError(f"tenant is not active: {membership.tenant_id}")

        group_ids = tuple(
            await self._session.scalars(
                select(Group.id)
                .join(GroupMembership, GroupMembership.group_id == Group.id)
                .where(
                    GroupMembership.user_id == user_id,
                    GroupMembership.status == ACTIVE_STATUS,
                    GroupMembership.deleted_at.is_(None),
                    Group.tenant_id == membership.tenant_id,
                    Group.status == ACTIVE_STATUS,
                    Group.deleted_at.is_(None),
                )
                .order_by(Group.id)
            )
        )
        tenant_grants, platform_permissions = await self._grants(
            user_id, membership.tenant_id, group_ids
        )
        role_codes, permission_codes = tenant_grants
        return AuthContext(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            tenant_id=membership.tenant_id,
            permission_codes=permission_codes,
            group_ids=group_ids,
            role_codes=role_codes,
            platform_permissions=platform_permissions,
        )

    async def _grants(
        self,
        user_id: UUID,
        tenant_id: UUID | None,
        group_ids: tuple[UUID, ...],
    ) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], tuple[str, ...]]:
        """Read tenant-scope and platform-scope grants in one query.

        Direct and group-held assignments are resolved identically: a group is
        a principal, not a second kind of permission.
        """

        principal = RoleAssignment.user_id == user_id
        if group_ids:
            principal = or_(principal, RoleAssignment.group_id.in_(group_ids))
        platform_scope = and_(
            RoleAssignment.tenant_id.is_(None), RoleAssignment.item_id.is_(None)
        )
        scope = (
            or_(platform_scope, RoleAssignment.tenant_id == tenant_id)
            if tenant_id is not None
            else platform_scope
        )
        rows = (
            await self._session.execute(
                select(Role.scope_type, Role.code, RolePermission.permission_code)
                .join(RoleAssignment, RoleAssignment.role_id == Role.id)
                .join(RolePermission, RolePermission.granted_by(Role.id))
                .where(
                    Role.status == ACTIVE_STATUS,
                    RoleAssignment.deleted_at.is_(None),
                    principal,
                    scope,
                )
            )
        ).all()
        role_codes: set[str] = set()
        permissions: set[str] = set()
        platform_permissions: set[str] = set()
        for scope_type, role_code, permission_code in rows:
            if scope_type == PLATFORM_SCOPE:
                platform_permissions.add(permission_code)
                continue
            role_codes.add(role_code)
            permissions.add(permission_code)
        return (
            (tuple(sorted(role_codes)), tuple(sorted(permissions))),
            tuple(sorted(platform_permissions)),
        )

    async def list_active_tenant_memberships(
        self, user_id: UUID
    ) -> tuple[TenantMembershipSummary, ...]:
        """Return workspaces the user may select as an active tenant."""

        await self.get_user(user_id)
        tenants = list(
            await self._session.scalars(
                select(Tenant)
                .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
                .where(
                    TenantMembership.user_id == user_id,
                    TenantMembership.status == ACTIVE_STATUS,
                    TenantMembership.deleted_at.is_(None),
                    Tenant.status == ACTIVE_STATUS,
                )
                .order_by(Tenant.created_at, Tenant.id)
            )
        )
        if not tenants:
            return ()
        grants = await self._tenant_grants_by_tenant(user_id)
        return tuple(
            TenantMembershipSummary(
                tenant_id=tenant.id,
                tenant_code=tenant.code,
                tenant_name=tenant.name,
                role_codes=grants.get(tenant.id, ((), ()))[0],
                permissions=grants.get(tenant.id, ((), ()))[1],
            )
            for tenant in tenants
        )

    async def _tenant_grants_by_tenant(
        self, user_id: UUID
    ) -> dict[UUID, tuple[tuple[str, ...], tuple[str, ...]]]:
        """Read every tenant-scope grant the user holds, across all workspaces."""

        held_group = (
            select(GroupMembership.group_id)
            .join(Group, Group.id == GroupMembership.group_id)
            .where(
                GroupMembership.user_id == user_id,
                GroupMembership.status == ACTIVE_STATUS,
                GroupMembership.deleted_at.is_(None),
                Group.status == ACTIVE_STATUS,
                Group.deleted_at.is_(None),
            )
        )
        rows = (
            await self._session.execute(
                select(
                    RoleAssignment.tenant_id,
                    Role.code,
                    RolePermission.permission_code,
                )
                .join(RoleAssignment, RoleAssignment.role_id == Role.id)
                .join(RolePermission, RolePermission.granted_by(Role.id))
                .where(
                    Role.status == ACTIVE_STATUS,
                    Role.scope_type == TENANT_SCOPE,
                    RoleAssignment.deleted_at.is_(None),
                    RoleAssignment.tenant_id.is_not(None),
                    or_(
                        RoleAssignment.user_id == user_id,
                        RoleAssignment.group_id.in_(held_group),
                    ),
                )
            )
        ).all()
        codes: dict[UUID, set[str]] = {}
        permissions: dict[UUID, set[str]] = {}
        for tenant_id, role_code, permission_code in rows:
            codes.setdefault(tenant_id, set()).add(role_code)
            permissions.setdefault(tenant_id, set()).add(permission_code)
        return {
            tenant_id: (
                tuple(sorted(codes[tenant_id])),
                tuple(sorted(permissions.get(tenant_id, set()))),
            )
            for tenant_id in codes
        }

    async def require_permissions(
        self,
        user_id: UUID,
        *permission_codes: str,
        tenant_id: UUID | None = None,
    ) -> AuthContext:
        context = await self.get_context(user_id, tenant_id=tenant_id)
        if not context.has_permissions(*permission_codes):
            required = ", ".join(sorted(permission_codes))
            raise AuthorizationError(f"missing required permissions: {required}")
        return context

    async def _membership(
        self, user_id: UUID, tenant_id: UUID | None
    ) -> TenantMembership | None:
        if tenant_id is not None:
            return await self._session.get(
                TenantMembership, {"user_id": user_id, "tenant_id": tenant_id}
            )
        memberships = list(
            await self._session.scalars(
                select(TenantMembership).where(
                    TenantMembership.user_id == user_id,
                    TenantMembership.deleted_at.is_(None),
                )
            )
        )
        if len(memberships) > 1:
            raise AuthorizationError("tenant ID is required for a multi-tenant user")
        return memberships[0] if memberships else None


async def resolve_agent_access(
    session_factory: SessionFactory, *, user_id: str, tenant_id: str
) -> AuthContext:
    """Re-resolve the authenticated caller behind an agent tool call.

    A tool receives only the tenant and user identifiers the chat request was
    authenticated with. Item-level authorization also needs the caller's admin
    state and group membership, so those are read back fail-closed from the
    database rather than trusted from the model-facing context.
    """

    try:
        user = UUID(user_id)
        tenant = UUID(tenant_id)
    except (TypeError, ValueError) as exc:
        raise AuthorizationError("agent context carries an invalid identity") from exc
    async with session_factory() as session:
        return await IdentityStoreService(session).get_context(user, tenant_id=tenant)


def _normalize_email(value: str) -> str:
    email = _required_text(value, "email", 255).casefold()
    if "@" not in email:
        raise ValueError("email must contain @")
    return email


def _normalize_code(value: str, field_name: str, max_length: int = 64) -> str:
    return _required_text(value, field_name, max_length).casefold()


def _tenant_permissions(values: Iterable[str]) -> list[str]:
    """Keep a tenant-defined role to capabilities a tenant may actually hold."""

    codes = sorted({_normalize_code(value, "permission code") for value in values})
    for code in codes:
        permission = PERMISSIONS_BY_CODE.get(code)
        if permission is None or TENANT_SCOPE not in permission.scopes:
            raise ValueError(f"unknown tenant permission code: {code}")
    return codes


def _required_text(value: str, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    return normalized


def _optional_text(
    value: str | None,
    field_name: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name, max_length)


__all__ = ["IdentityStoreService", "resolve_agent_access"]
