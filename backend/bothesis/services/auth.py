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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bothesis.db.models import (
    Group,
    GroupMembership,
    Role,
    Tenant,
    TenantMembership,
    User,
)
from bothesis.services import (
    ACTIVE_STATUS,
    AuthContext,
    AuthorizationError,
    IdentityConflictError,
    IdentityInactiveError,
    IdentityNotFoundError,
    INACTIVE_STATUS,
)


class AuthService:
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
        if user is None or (not include_inactive and user.status != ACTIVE_STATUS):
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
        if user is None or (not include_inactive and user.status != ACTIVE_STATUS):
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

    async def set_user_status(self, user_id: UUID, status: str) -> User:
        user = await self.get_user(user_id, include_inactive=True)
        user.status = _required_text(status, "user status", 16).casefold()
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

    async def create_role(
        self,
        tenant_id: UUID,
        code: str,
        display_name: str,
        *,
        permission_codes: Iterable[str] = (),
    ) -> Role:
        await self.get_tenant(tenant_id)
        normalized_code = _normalize_code(code, "role code")
        existing = await self._session.scalar(
            select(Role.id).where(
                Role.tenant_id == tenant_id,
                Role.code == normalized_code,
            )
        )
        if existing is not None:
            raise IdentityConflictError(
                f"role code already exists in tenant: {normalized_code}"
            )

        role = Role(
            tenant_id=tenant_id,
            code=normalized_code,
            display_name=_required_text(display_name, "role display name", 255),
            permission_codes=_normalize_codes(permission_codes, "permission code"),
        )
        self._session.add(role)
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
            Role.tenant_id == tenant_id,
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
        await self.get_tenant(tenant_id, include_inactive=include_inactive)
        statement = select(Role).where(Role.tenant_id == tenant_id)
        if not include_inactive:
            statement = statement.where(Role.status == ACTIVE_STATUS)
        result = await self._session.scalars(statement.order_by(Role.code))
        return list(result)

    async def update_role(
        self,
        tenant_id: UUID,
        role_id: UUID,
        *,
        display_name: str | None = None,
        permission_codes: Iterable[str] | None = None,
    ) -> Role:
        role = await self.get_role(tenant_id, role_id, include_inactive=True)
        if display_name is not None:
            role.display_name = _required_text(display_name, "role display name", 255)
        if permission_codes is not None:
            role.permission_codes = _normalize_codes(
                permission_codes, "permission code"
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
        role.status = _required_text(status, "role status", 16).casefold()
        await self._session.flush()
        return role

    async def assign_membership(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role_id: UUID,
    ) -> TenantMembership:
        await self.get_user(user_id)
        await self.get_tenant(tenant_id)
        await self.get_role(tenant_id, role_id)

        membership = await self._session.get(
            TenantMembership, {"user_id": user_id, "tenant_id": tenant_id}
        )
        if membership is None:
            membership = TenantMembership(
                user_id=user_id,
                tenant_id=tenant_id,
                role_id=role_id,
                joined_at=datetime.now(UTC),
            )
            self._session.add(membership)
        else:
            membership.role_id = role_id
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
        membership.status = INACTIVE_STATUS
        membership.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def get_context(
        self, user_id: UUID, *, tenant_id: UUID | None = None
    ) -> AuthContext:
        user = await self._session.scalar(
            select(User)
            .options(
                selectinload(User.tenant_memberships).joinedload(TenantMembership.tenant),
                selectinload(User.tenant_memberships).joinedload(TenantMembership.role),
            )
            .where(User.id == user_id)
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise IdentityNotFoundError(f"user not found: {user_id}")
        if user.status != ACTIVE_STATUS:
            raise IdentityInactiveError(f"user is not active: {user_id}")

        memberships = [
            value
            for value in user.tenant_memberships
            if value.deleted_at is None
            and (tenant_id is None or value.tenant_id == tenant_id)
        ]
        if tenant_id is None and len(memberships) > 1:
            raise AuthorizationError("tenant ID is required for a multi-tenant user")
        membership = memberships[0] if memberships else None
        if membership is None or membership.deleted_at is not None:
            if tenant_id is not None:
                raise AuthorizationError("user is not a member of the requested tenant")
            return AuthContext(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                tenant_id=None,
                role_id=None,
                role_code=None,
                permission_codes=(),
                group_ids=(),
            )

        if membership.status != ACTIVE_STATUS:
            raise IdentityInactiveError(f"membership is not active: {user_id}")
        if membership.tenant.status != ACTIVE_STATUS:
            raise IdentityInactiveError(f"tenant is not active: {membership.tenant_id}")
        if membership.role.status != ACTIVE_STATUS:
            raise IdentityInactiveError(f"role is not active: {membership.role_id}")
        if membership.role.tenant_id != membership.tenant_id:
            raise AuthorizationError("membership role belongs to a different tenant")

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

        return AuthContext(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            tenant_id=membership.tenant_id,
            role_id=membership.role_id,
            role_code=membership.role.code,
            permission_codes=tuple(sorted(set(membership.role.permission_codes))),
            group_ids=group_ids,
        )

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


def _normalize_email(value: str) -> str:
    email = _required_text(value, "email", 255).casefold()
    if "@" not in email:
        raise ValueError("email must contain @")
    return email


def _normalize_code(value: str, field_name: str, max_length: int = 64) -> str:
    return _required_text(value, field_name, max_length).casefold()


def _normalize_codes(
    values: Iterable[str],
    field_name: str,
    max_length: int = 64,
) -> list[str]:
    return sorted({_normalize_code(value, field_name, max_length) for value in values})


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


__all__ = ["AuthService"]
