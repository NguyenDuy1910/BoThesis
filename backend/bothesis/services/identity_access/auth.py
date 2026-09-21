"""Verified-provider sign-in and access-session transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import AccessSession, AuthIdentity, Conversation, Role, Tenant, User
from bothesis.services import (
    ACTIVE_STATUS,
    AuthContext,
    PLATFORM_ADMIN_ROLE,
    TENANT_ADMIN_ROLE,
    AuthenticationError,
    AuthenticationSession,
    AuthorizationError,
    IdentityConflictError,
    IdentityInactiveError,
    IdentityNotFoundError,
    TenantMembershipSummary,
    VerifiedGoogleIdentity,
)
from bothesis.services.audit import AuditService
from bothesis.services.identity_access.access_session import AccessSessionService
from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services.identity_access.jwt_tokens import JwtTokenService
from bothesis.services.identity_access.role_assignments import RoleAssignmentService
from bothesis.services.identity_access.passwords import PasswordCredentialService


class AuthenticationService:
    """Provision durable users and issue revocable tenant-scoped sessions."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        tokens: JwtTokenService,
        platform_admin_emails: frozenset[str] = frozenset(),
        public_tenant_code: str | None = None,
        guest_session_expires_in_seconds: int = 86_400,
    ) -> None:
        self._session = session
        self._identities = IdentityStoreService(session)
        self._access_sessions = AccessSessionService(session)
        self._assignments = RoleAssignmentService(session)
        self._tokens = tokens
        self._platform_admin_emails = platform_admin_emails
        self._public_tenant_code = public_tenant_code
        self._guest_session_expires_in_seconds = guest_session_expires_in_seconds

    async def create_account(
        self,
        *,
        email: str,
        password: str,
        username: str | None = None,
        display_name: str | None = None,
        guest_session_id: UUID | None = None,
    ) -> AuthenticationSession:
        """Create one local Account and issue its first canonical Session."""

        user = await self._identities.create_user(
            email,
            username=username,
            password_hash=PasswordCredentialService.hash(password),
            display_name=display_name,
        )
        await self._create_personal_workspace(user)
        return await self._issue_user_session(
            user,
            authentication_method="password",
            guest_session_id=guest_session_id,
        )

    async def create_session_request(
        self,
        *,
        method: str,
        email: str | None = None,
        password: str | None = None,
        credential: str | None = None,
        guest_session_id: UUID | None = None,
    ) -> AuthenticationSession:
        """Dispatch typed auth methods into one Session creation operation."""

        if method == "guest":
            return await self.create_guest_session()
        if method == "password":
            if email is None or password is None:
                raise AuthenticationError("email or password is incorrect")
            try:
                user = await self._identities.get_user_by_email(email)
            except IdentityNotFoundError as exc:
                raise AuthenticationError("email or password is incorrect") from exc
            if user.password_hash is None or not PasswordCredentialService.verify(
                password, user.password_hash
            ):
                raise AuthenticationError("email or password is incorrect")
            return await self._issue_user_session(
                user,
                authentication_method="password",
                guest_session_id=guest_session_id,
            )
        if method == "google":
            if credential is None:
                raise AuthenticationError("google credential is required")
            raise AuthenticationError(
                "google credentials must be verified at the API composition boundary"
            )
        raise AuthenticationError("unsupported authentication method")

    async def update_session(
        self, *, current_session_id: UUID, active_workspace_id: UUID
    ) -> AuthenticationSession:
        return await self.create_session(
            current_session_id=current_session_id, tenant_id=active_workspace_id
        )

    async def invalidate_session(self, session_id: UUID) -> None:
        row = await self._access_sessions.active(session_id, lock=True)
        self._access_sessions.revoke(row)
        await self._session.flush()

    async def current_session(self, session_id: UUID):
        row = await self._access_sessions.active(session_id)
        if row.kind == "guest":
            tenant = await self._identities.get_tenant(row.tenant_id)
            role_codes, permissions = await self._identities.public_access(tenant)
            context = AuthContext(
                session_id=row.id,
                session_kind="guest",
                token_version=row.token_version,
                user_id=None,
                email=None,
                display_name="Guest",
                tenant_id=row.tenant_id,
                permission_codes=permissions,
                group_ids=(),
                role_codes=role_codes,
            )
            return row, context, (self._public_summary(tenant, role_codes, permissions),)
        if row.user_id is None:
            raise AuthenticationError("user session has no subject")
        context = await self._identities.get_context(row.user_id, tenant_id=row.tenant_id)
        memberships = await self._identities.list_active_tenant_memberships(row.user_id)
        return row, context, memberships

    async def complete_password_login(
        self,
        *,
        username: str,
        password: str,
        guest_session_id: UUID | None = None,
    ) -> AuthenticationSession:
        """Verify a local credential and issue a tenant-scoped session."""

        try:
            user = await self._identities.get_user_by_username(username)
        except IdentityNotFoundError as exc:
            raise AuthenticationError("username or password is incorrect") from exc
        if user.password_hash is None or not PasswordCredentialService.verify(
            password, user.password_hash
        ):
            raise AuthenticationError("username or password is incorrect")
        return await self._issue_user_session(
            user,
            authentication_method="password",
            guest_session_id=guest_session_id,
        )

    async def create_password_account(
        self,
        *,
        username: str,
        email: str,
        password: str,
        display_name: str | None = None,
        guest_session_id: UUID | None = None,
    ) -> AuthenticationSession:
        """Create a local account with a personal workspace."""

        user = await self._identities.create_user(
            email,
            username=username,
            password_hash=PasswordCredentialService.hash(password),
            display_name=display_name,
        )
        await self._create_personal_workspace(user)
        return await self._issue_user_session(
            user,
            authentication_method="password",
            guest_session_id=guest_session_id,
        )

    async def create_guest_session(self) -> AuthenticationSession:
        """Create one anonymous security session in configured public workspace."""

        tenant = await self._public_tenant()
        row, context = await self._access_sessions.create_guest(
            tenant, expires_in_seconds=self._guest_session_expires_in_seconds
        )
        access_token, token_expires_at = self._tokens.issue(
            context, expires_in_seconds=self._guest_session_expires_in_seconds
        )
        return AuthenticationSession(
            access_token=access_token,
            expires_at=min(row.expires_at, token_expires_at),
            session_id=row.id,
            user_id=None,
            email=None,
            display_name="Guest",
            active_tenant_id=tenant.id,
            permissions=context.permission_codes,
            tenants=(self._public_summary(tenant, context.role_codes, context.permission_codes),),
            platform_permissions=(),
            session_kind="guest",
        )

    async def complete_google_login(
        self,
        identity: VerifiedGoogleIdentity,
        *,
        guest_session_id: UUID | None = None,
    ) -> AuthenticationSession:
        """Link verified Google subject, upgrade guest state, and issue user session."""

        user, auth_identity, personal_tenant_id = await self._find_or_provision_user(
            identity
        )
        await self._grant_configured_platform_admin(user)
        parent: AccessSession | None = None
        if guest_session_id is not None:
            parent = await self._access_sessions.active(guest_session_id, lock=True)
            if parent.kind != "guest":
                raise AuthorizationError("only a guest session can be upgraded")

        memberships = await self._identities.list_active_tenant_memberships(user.id)
        if not memberships and parent is None:
            raise AuthorizationError("user has no active tenant membership")
        active_tenant_id = (
            parent.tenant_id
            if parent is not None
            else personal_tenant_id
            or _default_tenant_id(memberships, user_id=str(user.id))
        )
        row, context = await self._access_sessions.create_user(
            user=user,
            tenant_id=active_tenant_id,
            auth_identity=auth_identity,
            authentication_method="oidc",
            expires_in_seconds=self._tokens.expires_in_seconds,
            parent=parent,
            transition_reason="identity_upgrade" if parent is not None else None,
        )
        if parent is not None:
            await self._session.execute(
                update(Conversation)
                .where(
                    Conversation.created_by_session_id == parent.id,
                    Conversation.tenant_id == parent.tenant_id,
                    Conversation.owner_user_id.is_(None),
                )
                .values(owner_user_id=user.id)
            )
        access_token, expires_at = self._tokens.issue(context)
        return AuthenticationSession(
            access_token=access_token,
            expires_at=min(row.expires_at, expires_at),
            session_id=row.id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            active_tenant_id=active_tenant_id,
            permissions=context.permission_codes,
            tenants=await self._session_tenants(memberships, active_tenant_id, context),
            platform_permissions=context.platform_permissions,
            session_kind="user",
        )

    async def _issue_user_session(
        self,
        user: User,
        *,
        authentication_method: str,
        guest_session_id: UUID | None,
    ) -> AuthenticationSession:
        await self._grant_configured_platform_admin(user)
        parent: AccessSession | None = None
        if guest_session_id is not None:
            parent = await self._access_sessions.active(guest_session_id, lock=True)
            if parent.kind != "guest":
                raise AuthorizationError("only a guest session can be upgraded")
        memberships = await self._identities.list_active_tenant_memberships(user.id)
        if not memberships and parent is None:
            raise AuthorizationError("user has no active tenant membership")
        active_tenant_id = (
            parent.tenant_id
            if parent is not None
            else _default_tenant_id(memberships, user_id=str(user.id))
        )
        row, context = await self._access_sessions.create_user(
            user=user,
            tenant_id=active_tenant_id,
            auth_identity=None,
            authentication_method=authentication_method,
            expires_in_seconds=self._tokens.expires_in_seconds,
            parent=parent,
            transition_reason="identity_upgrade" if parent is not None else None,
        )
        if parent is not None:
            await self._session.execute(
                update(Conversation)
                .where(
                    Conversation.created_by_session_id == parent.id,
                    Conversation.tenant_id == parent.tenant_id,
                    Conversation.owner_user_id.is_(None),
                )
                .values(owner_user_id=user.id)
            )
        access_token, expires_at = self._tokens.issue(context)
        return AuthenticationSession(
            access_token=access_token,
            expires_at=min(row.expires_at, expires_at),
            session_id=row.id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            active_tenant_id=active_tenant_id,
            permissions=context.permission_codes,
            tenants=await self._session_tenants(memberships, active_tenant_id, context),
            platform_permissions=context.platform_permissions,
            session_kind="user",
        )

    async def create_session(
        self, *, current_session_id: UUID, tenant_id: UUID
    ) -> AuthenticationSession:
        """Replace current user session with one selecting another membership."""

        parent = await self._access_sessions.active(current_session_id, lock=True)
        if parent.kind != "user" or parent.user_id is None:
            raise AuthorizationError("sign in is required for workspace selection")
        user = await self._identities.get_user(parent.user_id)
        memberships = await self._identities.list_active_tenant_memberships(user.id)
        if tenant_id not in {membership.tenant_id for membership in memberships}:
            tenant = await self._identities.get_tenant(tenant_id)
            try:
                await self._identities.public_access(tenant)
            except AuthorizationError as exc:
                raise AuthorizationError(
                    f"user is not a member of tenant: {tenant_id}"
                ) from exc
        auth_identity = (
            await self._session.get(AuthIdentity, parent.auth_identity_id)
            if parent.auth_identity_id is not None
            else None
        )
        if auth_identity is None and parent.authentication_method not in {"internal", "password"}:
            raise AuthorizationError("session identity is unavailable")
        row, context = await self._access_sessions.create_user(
            user=user,
            tenant_id=tenant_id,
            auth_identity=auth_identity,
            authentication_method=parent.authentication_method,
            expires_in_seconds=self._tokens.expires_in_seconds,
            parent=parent,
            transition_reason="tenant_switch",
        )
        access_token, expires_at = self._tokens.issue(context)
        return AuthenticationSession(
            access_token=access_token,
            expires_at=min(row.expires_at, expires_at),
            session_id=row.id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            active_tenant_id=tenant_id,
            permissions=context.permission_codes,
            tenants=await self._session_tenants(memberships, tenant_id, context),
            platform_permissions=context.platform_permissions,
            session_kind="user",
        )

    async def _find_or_provision_user(
        self, identity: VerifiedGoogleIdentity
    ) -> tuple[User, AuthIdentity, UUID | None]:
        try:
            auth_identity = await self._identities.get_auth_identity(
                identity.issuer, identity.subject, include_disabled=True
            )
        except IdentityNotFoundError:
            auth_identity = None
        if auth_identity is not None:
            if auth_identity.status != ACTIVE_STATUS:
                raise IdentityInactiveError("external identity is disabled")
            user = await self._identities.get_user(
                auth_identity.user_id, include_inactive=True
            )
            if not user.status:
                raise IdentityInactiveError(f"user is not active: {user.id}")
            auth_identity.email = identity.email.casefold()
            auth_identity.email_verified = True
            auth_identity.last_authenticated_at = datetime.now(UTC)
            user.last_login_at = datetime.now(UTC)
            await self._session.flush()
            return user, auth_identity, None

        personal_tenant_id: UUID | None = None
        try:
            user = await self._identities.get_user_by_email(
                identity.email, include_inactive=True
            )
            if not user.status:
                raise IdentityInactiveError(f"user is not active: {user.id}")
        except IdentityNotFoundError:
            user, personal_tenant_id = await self._provision_personal_workspace(identity)
        try:
            async with self._session.begin_nested():
                auth_identity = await self._identities.create_auth_identity(
                    user.id,
                    protocol="oidc",
                    provider_key="google",
                    issuer=identity.issuer,
                    subject=identity.subject,
                    email=identity.email,
                    email_verified=True,
                    profile={"display_name": identity.display_name},
                )
        except IntegrityError:
            auth_identity = await self._identities.get_auth_identity(
                identity.issuer, identity.subject
            )
            if auth_identity.user_id != user.id:
                raise IdentityConflictError(
                    "external identity is already linked to another user"
                )
        user.last_login_at = datetime.now(UTC)
        await self._session.flush()
        return user, auth_identity, personal_tenant_id

    async def _provision_personal_workspace(
        self, identity: VerifiedGoogleIdentity
    ) -> tuple[User, UUID | None]:
        try:
            async with self._session.begin_nested():
                user = await self._identities.create_user(
                    identity.email, display_name=identity.display_name
                )
                display_name = user.display_name or user.email.partition("@")[0]
                tenant = await self._identities.create_tenant(
                    f"tenant-{user.id}", f"{display_name[:243].rstrip()}'s Workspace"
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
            user = await self._identities.get_user_by_email(
                identity.email, include_inactive=True
            )
            if not user.status:
                raise IdentityInactiveError(f"user is not active: {user.id}")
            return user, None

    async def _create_personal_workspace(self, user: User) -> UUID:
        tenant = await self._identities.create_tenant(
            f"tenant-{user.id}",
            f"{(user.display_name or user.username or user.email.partition('@')[0])[:243].rstrip()}'s Workspace",
        )
        await self._identities.assign_membership(user.id, tenant.id)
        await self._assignments.replace_tenant_roles(
            user_id=user.id,
            tenant_id=tenant.id,
            role_ids=[await self._tenant_admin_role_id()],
            created_by_user_id=user.id,
        )
        return tenant.id

    async def _session_tenants(
        self,
        memberships: tuple[TenantMembershipSummary, ...],
        active_tenant_id: UUID,
        context,
    ) -> tuple[TenantMembershipSummary, ...]:
        if active_tenant_id in {membership.tenant_id for membership in memberships}:
            return memberships
        tenant = await self._identities.get_tenant(active_tenant_id)
        return (
            self._public_summary(tenant, context.role_codes, context.permission_codes),
            *memberships,
        )

    @staticmethod
    def _public_summary(
        tenant: Tenant, role_codes: tuple[str, ...], permissions: tuple[str, ...]
    ) -> TenantMembershipSummary:
        return TenantMembershipSummary(
            tenant_id=tenant.id,
            tenant_code=tenant.code,
            tenant_name=tenant.name,
            role_codes=role_codes,
            permissions=permissions,
        )

    async def _public_tenant(self) -> Tenant:
        if not self._public_tenant_code:
            raise AuthorizationError("public workspace is not configured")
        tenant = await self._session.scalar(
            select(Tenant).where(
                Tenant.code == self._public_tenant_code,
                Tenant.status == ACTIVE_STATUS,
                Tenant.visibility == "public",
            )
        )
        if tenant is None:
            raise AuthorizationError("configured public workspace is unavailable")
        return tenant

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
