"""Verified-provider sign-in and tenant-context switching."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Role, User
from bothesis.services.audit import AuditService
from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services.identity_access.jwt_tokens import JwtTokenService
from bothesis.services.identity_access.role_assignments import RoleAssignmentService
from bothesis.services import (
    ACTIVE_STATUS,
    PLATFORM_ADMIN_ROLE,
    TENANT_ADMIN_ROLE,
    AuthenticationSession,
    AuthorizationError,
    IdentityConflictError,
    IdentityInactiveError,
    IdentityNotFoundError,
    TenantMembershipSummary,
    VerifiedGoogleIdentity,
)


class AuthenticationService:
    """Provision a personal tenant after verified sign-in and issue active-context JWTs."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        tokens: JwtTokenService,
        platform_admin_emails: frozenset[str] = frozenset(),
    ) -> None:
        self._session = session
        self._identities = IdentityStoreService(session)
        self._assignments = RoleAssignmentService(session)
        self._tokens = tokens
        self._platform_admin_emails = platform_admin_emails

    async def complete_google_login(
        self, identity: VerifiedGoogleIdentity
    ) -> AuthenticationSession:
        """Persist a verified Google principal, provisioning its first workspace atomically."""

        user, personal_tenant_id = await self._find_or_provision_user(identity)
        await self._grant_configured_platform_admin(user)
        memberships = await self._identities.list_active_tenant_memberships(user.id)
        if not memberships:
            raise AuthorizationError("user has no active tenant membership")
        active_tenant_id = personal_tenant_id or _default_tenant_id(
            memberships, user_id=str(user.id)
        )
        context = await self._identities.get_context(user.id, tenant_id=active_tenant_id)
        access_token, expires_at = self._tokens.issue(context)
        return AuthenticationSession(
            access_token=access_token,
            expires_at=expires_at,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            active_tenant_id=active_tenant_id,
            permissions=context.permission_codes,
            tenants=memberships,
            platform_permissions=context.platform_permissions,
        )

    async def create_session(
        self, *, user_id: UUID, tenant_id: UUID
    ) -> AuthenticationSession:
        """Issue a session token for an active workspace the user may select."""

        await self._identities.get_user(user_id)
        memberships = await self._identities.list_active_tenant_memberships(user_id)
        # Platform administration is its own scope. It never admits an actor to
        # a workspace they are not a member of.
        if tenant_id not in {membership.tenant_id for membership in memberships}:
            raise AuthorizationError("user cannot select the requested workspace")
        try:
            context = await self._identities.get_context(user_id, tenant_id=tenant_id)
        except IdentityInactiveError as exc:
            raise AuthorizationError(
                "user cannot select the requested workspace"
            ) from exc
        access_token, expires_at = self._tokens.issue(context)
        return AuthenticationSession(
            access_token=access_token,
            expires_at=expires_at,
            user_id=context.user_id,
            email=context.email,
            display_name=context.display_name,
            active_tenant_id=tenant_id,
            permissions=context.permission_codes,
            tenants=memberships,
            platform_permissions=context.platform_permissions,
        )

    async def _find_or_provision_user(
        self, identity: VerifiedGoogleIdentity
    ) -> tuple[User, UUID | None]:
        try:
            user = await self._identities.get_user_by_email(
                identity.email, include_inactive=True
            )
        except IdentityNotFoundError:
            return await self._provision_personal_workspace(identity)
        if not user.status:
            raise IdentityInactiveError(f"user is not active: {user.id}")
        user.last_login_at = datetime.now(UTC)
        await self._session.flush()
        return user, None

    async def _provision_personal_workspace(
        self, identity: VerifiedGoogleIdentity
    ) -> tuple[User, UUID | None]:
        """Use a savepoint so concurrent first logins converge on the same user."""

        try:
            async with self._session.begin_nested():
                user = await self._identities.create_user(
                    identity.email, display_name=identity.display_name
                )
                user.last_login_at = datetime.now(UTC)
                display_name = user.display_name or user.email.partition("@")[0]
                workspace_name = f"{display_name[:243].rstrip()}'s Workspace"
                tenant = await self._identities.create_tenant(
                    f"tenant-{user.id}", workspace_name
                )
                await self._identities.assign_membership(user.id, tenant.id)
                await self._assignments.replace_tenant_roles(
                    user_id=user.id,
                    tenant_id=tenant.id,
                    role_ids=[await self._tenant_admin_role_id()],
                    created_by_user_id=user.id,
                )
                return user, tenant.id
        except (IdentityConflictError, IntegrityError):
            # A concurrent request won the unique-email insert. Its workspace
            # is committed with that row, so this request becomes a normal login.
            user = await self._identities.get_user_by_email(
                identity.email, include_inactive=True
            )
            if not user.status:
                raise IdentityInactiveError(f"user is not active: {user.id}")
            user.last_login_at = datetime.now(UTC)
            await self._session.flush()
            return user, None

    async def _tenant_admin_role_id(self) -> UUID:
        role = await self._session.scalar(
            select(Role).where(
                Role.code == TENANT_ADMIN_ROLE,
                Role.tenant_id.is_(None),
                Role.status == ACTIVE_STATUS,
            )
        )
        if role is None:
            raise IdentityNotFoundError(
                "system roles are missing; run the system role sync"
            )
        return role.id

    async def _grant_configured_platform_admin(self, user: User) -> None:
        """Turn the configured bootstrap allowlist into a real role assignment.

        Platform administration is a grant like any other, so it is recorded
        where every other grant lives and can be revoked the same way.
        """

        if user.email not in self._platform_admin_emails:
            return
        granted = await self._assignments.ensure_platform_role(
            user.id, PLATFORM_ADMIN_ROLE
        )
        if granted:
            await AuditService(self._session).record_platform_event(
                actor_user_id=user.id,
                action="role_assignment.platform_admin.granted",
                resource_type="user",
                resource_id=str(user.id),
                details={"source": "configured_platform_admin_emails"},
            )


def _default_tenant_id(
    memberships: tuple[TenantMembershipSummary, ...], *, user_id: str
) -> UUID:
    personal_code = f"tenant-{user_id}"
    personal = next(
        (membership for membership in memberships if membership.tenant_code == personal_code),
        None,
    )
    return (personal or memberships[0]).tenant_id


__all__ = ["AuthenticationService"]
