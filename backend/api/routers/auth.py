"""Session-centered authentication API."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from api.deps import OptionalTokenClaims, Runtime, TokenClaims
from api.routers import (
    AccountCreate,
    AuthSession,
    CreateSessionRequest,
    CurrentSession,
    CurrentSessionUpdate,
    GoogleSessionCreate,
    PasswordSessionCreate,
    WorkspaceMembership,
)
from bothesis.db.engine import session_scope
from bothesis.services import AuthenticationSession

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/accounts", response_model=AuthSession, status_code=status.HTTP_201_CREATED, operation_id="createAccount")
async def create_account(body: AccountCreate, claims: OptionalTokenClaims, runtime: Runtime) -> AuthSession:
    async with session_scope(runtime.sessions()) as session:
        result = await runtime.authentication_service(session).create_account(
            email=str(body.email), password=body.password, username=body.username,
            display_name=body.display_name,
            guest_session_id=claims.session_id if claims and claims.session_kind == "guest" else None,
        )
    return _session_response(result)


@router.post("/sessions", response_model=AuthSession, operation_id="createSession")
async def create_session(body: CreateSessionRequest, claims: OptionalTokenClaims, runtime: Runtime) -> AuthSession:
    async with session_scope(runtime.sessions()) as session:
        authentication = runtime.authentication_service(session)
        guest_session_id = claims.session_id if claims and claims.session_kind == "guest" else None
        if isinstance(body, GoogleSessionCreate):
            identity = await runtime.google_identity_verifier().verify(body.credential or "")
            result = await authentication.complete_verified_external_session(identity, guest_session_id=guest_session_id)
        else:
            result = await authentication.create_session(
                method=body.method,
                email=str(body.email) if isinstance(body, PasswordSessionCreate) else None,
                password=body.password if isinstance(body, PasswordSessionCreate) else None,
                guest_session_id=guest_session_id,
            )
    return _session_response(result)


@router.get("/session", response_model=CurrentSession, operation_id="getCurrentSession")
async def get_current_session(claims: TokenClaims, runtime: Runtime) -> CurrentSession:
    async with session_scope(runtime.sessions()) as session:
        row, context, memberships = await runtime.authentication_service(session).current_session(claims.session_id)
    return CurrentSession(
        session_id=claims.session_id, expires_at=row.expires_at, user_id=context.user_id,
        email=context.email, display_name=context.display_name,
        active_workspace_id=context.tenant_id, permissions=list(context.permission_codes),
        platform_permissions=list(context.platform_permissions), session_kind=context.session_kind,
        workspaces=[
            WorkspaceMembership(
                id=workspace.tenant_id, code=workspace.tenant_code, name=workspace.tenant_name,
                role_codes=list(workspace.role_codes), permissions=list(workspace.permissions),
            )
            for workspace in memberships
        ],
    )


@router.patch("/session", response_model=AuthSession, operation_id="updateCurrentSession")
async def update_current_session(body: CurrentSessionUpdate, claims: TokenClaims, runtime: Runtime) -> AuthSession:
    async with session_scope(runtime.sessions()) as session:
        result = await runtime.authentication_service(session).update_session(
            current_session_id=claims.session_id, active_workspace_id=body.active_workspace_id
        )
    return _session_response(result)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteCurrentSession")
async def delete_current_session(claims: TokenClaims, runtime: Runtime) -> Response:
    async with session_scope(runtime.sessions()) as session:
        await runtime.authentication_service(session).invalidate_session(claims.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _session_response(result: AuthenticationSession) -> AuthSession:
    return AuthSession(
        access_token=result.access_token, expires_at=result.expires_at,
        session_id=result.session_id, user_id=result.user_id, email=result.email,
        display_name=result.display_name, active_workspace_id=result.active_tenant_id,
        permissions=list(result.permissions), platform_permissions=list(result.platform_permissions),
        session_kind=result.session_kind,
        workspaces=[
            WorkspaceMembership(
                id=workspace.tenant_id, code=workspace.tenant_code, name=workspace.tenant_name,
                role_codes=list(workspace.role_codes), permissions=list(workspace.permissions),
            )
            for workspace in result.tenants
        ],
    )


__all__ = ["router"]
