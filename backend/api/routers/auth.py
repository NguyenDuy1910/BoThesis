"""Authentication routes for verified Google sign-in and workspace sessions."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import Runtime, TokenClaims
from bothesis.db.engine import session_scope
from bothesis.services import AuthenticationSession

from api.routers import (
    AuthSessionResponse,
    AuthTenant,
    CreateAuthSessionRequest,
    GoogleCredentialRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=AuthSessionResponse)
async def complete_google_login(
    body: GoogleCredentialRequest,
    runtime: Runtime,
) -> AuthSessionResponse:
    """Verify a Google credential, then provision or resume the workspace session."""

    identity = await runtime.google_identity_verifier().verify(body.credential)
    async with session_scope(runtime.sessions()) as session:
        result = await runtime.authentication_service(session).complete_google_login(
            identity
        )
    return _response(result)


@router.post("/session", response_model=AuthSessionResponse)
async def create_session(
    body: CreateAuthSessionRequest,
    claims: TokenClaims,
    runtime: Runtime,
) -> AuthSessionResponse:
    """Issue a new session token for an active tenant membership."""

    async with session_scope(runtime.sessions()) as session:
        result = await runtime.authentication_service(session).create_session(
            user_id=claims.user_id, tenant_id=body.tenant_id
        )
    return _response(result)


def _response(result: AuthenticationSession) -> AuthSessionResponse:
    return AuthSessionResponse(
        access_token=result.access_token,
        expires_at=result.expires_at.isoformat(),
        user_id=result.user_id,
        email=result.email,
        display_name=result.display_name,
        active_tenant_id=result.active_tenant_id,
        permissions=list(result.permissions),
        platform_scopes=list(result.platform_scopes),
        tenants=[
            AuthTenant(
                id=tenant.tenant_id,
                code=tenant.tenant_code,
                name=tenant.tenant_name,
                role_id=tenant.role_id,
                role_code=tenant.role_code,
                permissions=list(tenant.permissions),
            )
            for tenant in result.tenants
        ],
    )


__all__ = ["router"]
