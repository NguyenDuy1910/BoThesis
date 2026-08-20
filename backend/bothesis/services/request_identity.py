"""Resolve a trusted request identity without embedding auth in file services."""

from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.services import AuthContext, AuthService, AuthorizationError


async def resolve_auth_context(
    request: Request,
    session: AsyncSession,
    *,
    claimed_user_id: str | UUID | None = None,
    claimed_tenant_id: str | UUID | None = None,
    allow_insecure_development_identity: bool = False,
) -> AuthContext:
    """Use injected middleware identity, or an explicitly enabled dev identity."""

    injected = getattr(request.state, "auth_context", None)
    if injected is not None:
        if not isinstance(injected, AuthContext):
            raise AuthorizationError("request auth context has an invalid type")
        _validate_tenant_claim(injected, claimed_tenant_id)
        return injected

    if not allow_insecure_development_identity:
        raise AuthorizationError("authenticated request context is required")

    raw_user_id = request.headers.get("X-Bothesis-User-Id") or claimed_user_id
    raw_tenant_id = request.headers.get("X-Bothesis-Tenant-Id") or claimed_tenant_id
    if raw_user_id is None:
        raise AuthorizationError("development user ID is required")
    try:
        user_id = raw_user_id if isinstance(raw_user_id, UUID) else UUID(raw_user_id)
    except (TypeError, ValueError) as exc:
        raise AuthorizationError("development user ID must be a UUID") from exc

    context = await AuthService(session).get_context(user_id)
    _validate_tenant_claim(context, raw_tenant_id)
    return context


def _validate_tenant_claim(
    context: AuthContext,
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
    if context.tenant_id != tenant_id:
        raise AuthorizationError("tenant claim does not match database membership")


__all__ = ["resolve_auth_context"]
