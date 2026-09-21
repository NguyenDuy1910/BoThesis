"""Durable access-session lifecycle and request-context resolution."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import AccessSession, AuthIdentity, Tenant, User
from bothesis.services import (
    ACTIVE_STATUS,
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    JwtClaims,
)
from bothesis.services.identity_access.identity_store import IdentityStoreService


class AccessSessionService:
    """Create, transition, and validate one tenant-scoped security session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identities = IdentityStoreService(session)

    async def create_guest(
        self,
        tenant: Tenant,
        *,
        expires_in_seconds: int,
        metadata: dict[str, object] | None = None,
    ) -> tuple[AccessSession, AuthContext]:
        if tenant.status != ACTIVE_STATUS or tenant.visibility != "public":
            raise AuthorizationError("public workspace is unavailable")
        role_codes, permissions = await self._identities.public_access(tenant)
        now = datetime.now(UTC)
        row = AccessSession(
            tenant_id=tenant.id,
            kind="guest",
            authentication_method="anonymous",
            assurance_level="aal0",
            expires_at=now + timedelta(seconds=expires_in_seconds),
            idle_expires_at=now + timedelta(seconds=expires_in_seconds),
            last_seen_at=now,
            metadata_=dict(metadata or {}),
        )
        self._session.add(row)
        await self._session.flush()
        return row, AuthContext(
            session_id=row.id,
            session_kind="guest",
            token_version=row.token_version,
            user_id=None,
            email=None,
            display_name="Guest",
            tenant_id=tenant.id,
            permission_codes=permissions,
            group_ids=(),
            role_codes=role_codes,
        )

    async def create_user(
        self,
        *,
        user: User,
        tenant_id: UUID,
        auth_identity: AuthIdentity | None,
        authentication_method: str,
        expires_in_seconds: int,
        parent: AccessSession | None = None,
        transition_reason: str | None = None,
    ) -> tuple[AccessSession, AuthContext]:
        context = await self._identities.get_context(user.id, tenant_id=tenant_id)
        now = datetime.now(UTC)
        row = AccessSession(
            tenant_id=tenant_id,
            user_id=user.id,
            auth_identity_id=auth_identity.id if auth_identity is not None else None,
            kind="user",
            authentication_method=authentication_method,
            assurance_level="aal1",
            parent_session_id=parent.id if parent is not None else None,
            transition_reason=transition_reason,
            expires_at=now + timedelta(seconds=expires_in_seconds),
            last_seen_at=now,
        )
        self._session.add(row)
        if parent is not None:
            self._end(parent, status="superseded", reason=transition_reason or "replaced")
        await self._session.flush()
        return row, replace(
            context,
            session_id=row.id,
            session_kind="user",
            token_version=row.token_version,
        )

    async def internal_user(
        self, *, user: User, tenant_id: UUID
    ) -> AuthContext:
        """Reuse one explicit development-only session instead of minting per request."""

        now = datetime.now(UTC)
        row = await self._session.scalar(
            select(AccessSession).where(
                AccessSession.user_id == user.id,
                AccessSession.tenant_id == tenant_id,
                AccessSession.kind == "user",
                AccessSession.authentication_method == "internal",
                AccessSession.status == "active",
                AccessSession.expires_at > now,
            )
        )
        context = await self._identities.get_context(user.id, tenant_id=tenant_id)
        if row is None:
            row, context = await self.create_user(
                user=user,
                tenant_id=tenant_id,
                auth_identity=None,
                authentication_method="internal",
                expires_in_seconds=86_400,
            )
            return context
        return replace(
            context,
            session_id=row.id,
            session_kind="user",
            token_version=row.token_version,
        )

    async def active(
        self, session_id: UUID, *, lock: bool = False
    ) -> AccessSession:
        statement = select(AccessSession).where(AccessSession.id == session_id)
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise AuthenticationError("access session is unavailable")
        now = datetime.now(UTC)
        expired = row.expires_at <= now or (
            row.idle_expires_at is not None and row.idle_expires_at <= now
        )
        if expired and row.status == "active":
            self._end(row, status="expired", reason="session_expired")
            await self._session.flush()
        if row.status != "active" or expired:
            raise AuthenticationError("access session is unavailable or expired")
        return row

    def revoke(self, row: AccessSession, *, reason: str = "logout") -> None:
        """Invalidate one durable session without deleting its audit trail."""

        self._end(row, status="revoked", reason=reason)

    async def resolve(self, claims: JwtClaims) -> AuthContext:
        row = await self.active(claims.session_id)
        if (
            row.tenant_id != claims.active_tenant_id
            or row.user_id != claims.user_id
            or row.kind != claims.session_kind
            or row.token_version != claims.token_version
        ):
            raise AuthenticationError("access token no longer matches its session")
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
        else:
            if row.user_id is None:
                raise AuthenticationError("user session has no subject")
            if row.auth_identity_id is not None:
                identity = await self._session.get(AuthIdentity, row.auth_identity_id)
                if (
                    identity is None
                    or identity.status != ACTIVE_STATUS
                    or identity.user_id != row.user_id
                ):
                    raise AuthenticationError("session identity is unavailable")
            context = replace(
                await self._identities.get_context(row.user_id, tenant_id=row.tenant_id),
                session_id=row.id,
                session_kind="user",
                token_version=row.token_version,
            )
        if (
            context.email != claims.email
            or context.permission_codes != claims.permissions
            or context.platform_permissions != claims.platform_permissions
        ):
            raise AuthenticationError(
                "access token no longer reflects current authorization"
            )
        now = datetime.now(UTC)
        if row.last_seen_at is None or now - row.last_seen_at >= timedelta(minutes=5):
            row.last_seen_at = now
            await self._session.flush()
        return context

    @staticmethod
    def _end(row: AccessSession, *, status: str, reason: str) -> None:
        row.status = status
        row.ended_at = datetime.now(UTC)
        row.end_reason = reason


__all__ = ["AccessSessionService"]
