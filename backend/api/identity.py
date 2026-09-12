"""Resolve a trusted request identity without embedding auth in file services."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services import (
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    JwtClaims,
)


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    """Trusted identity inputs received at the HTTP boundary."""

    auth_context: AuthContext | None = None
    token_claims: JwtClaims | None = None
    user_id: str | UUID | None = None
    tenant_id: str | UUID | None = None


async def resolve_auth_context(
    identity: RequestIdentity,
    session: AsyncSession,
    *,
    claimed_user_id: str | UUID | None = None,
    claimed_tenant_id: str | UUID | None = None,
    allow_insecure_development_identity: bool = False,
) -> AuthContext:
    """Use injected middleware identity, or an explicitly enabled dev identity."""

    injected = identity.auth_context
    if injected is not None:
        if not isinstance(injected, AuthContext):
            raise AuthorizationError("request auth context has an invalid type")
        _validate_tenant_claim(injected, claimed_tenant_id)
        return injected

    token_claims = identity.token_claims
    if token_claims is not None:
        _validate_tenant_claim(token_claims, claimed_tenant_id)
        context = await IdentityStoreService(session).get_context(
            token_claims.user_id, tenant_id=token_claims.active_tenant_id
        )
        if (
            context.email != token_claims.email
            or context.tenant_id != token_claims.active_tenant_id
            or tuple(sorted(set(context.permission_codes))) != token_claims.permissions
            or context.platform_scopes != token_claims.platform_scopes
        ):
            raise AuthenticationError(
                "access token no longer reflects the active tenant membership"
            )
        return context

    if not allow_insecure_development_identity:
        raise AuthorizationError("authenticated request context is required")

    raw_user_id = identity.user_id or claimed_user_id
    raw_tenant_id = identity.tenant_id or claimed_tenant_id
    if raw_user_id is None:
        raise AuthorizationError("development user ID is required")
    try:
        user_id = raw_user_id if isinstance(raw_user_id, UUID) else UUID(raw_user_id)
    except (TypeError, ValueError) as exc:
        raise AuthorizationError("development user ID must be a UUID") from exc

    tenant_id: UUID | None = None
    if raw_tenant_id is not None:
        try:
            tenant_id = (
                raw_tenant_id
                if isinstance(raw_tenant_id, UUID)
                else UUID(raw_tenant_id)
            )
        except (TypeError, ValueError) as exc:
            raise AuthorizationError("tenant ID must be a UUID") from exc
    context = await IdentityStoreService(session).get_context(user_id, tenant_id=tenant_id)
    _validate_tenant_claim(context, raw_tenant_id)
    return context


def _validate_tenant_claim(
    context: AuthContext | JwtClaims,
    claimed_tenant_id: str | UUID | None,
) -> None:
    if claimed_tenant_id is None:
        return
    try:
        tenant_id = (
            claimed_tenant_id
            if isinstance(claimed_tenant_id, UUID)
            else UUID(claimed_tenant_id)
        )
    except (TypeError, ValueError) as exc:
        raise AuthorizationError("tenant ID must be a UUID") from exc
    active_tenant_id = (
        context.tenant_id
        if isinstance(context, AuthContext)
        else context.active_tenant_id
    )
    if active_tenant_id != tenant_id:
        raise AuthorizationError("tenant claim does not match database membership")


__all__ = ["RequestIdentity", "resolve_auth_context"]
