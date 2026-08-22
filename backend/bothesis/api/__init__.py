"""Validated Admin API inputs and error-boundary registration."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.exc import IntegrityError

from bothesis.services import (
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    AuthorizationError,
    IdentityInactiveError,
    IdentityNotFoundError,
)


class AdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpaceUpdate(AdminRequest):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    settings: dict[str, Any] | None = None


class UserCreate(AdminRequest):
    email: EmailStr
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role_id: UUID
    group_ids: list[UUID] = Field(default_factory=list)


class UserUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role_id: UUID | None = None
    status: Literal["active", "inactive"] | None = None
    group_ids: list[UUID] | None = None


class RoleCreate(AdminRequest):
    code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    permission_codes: list[str] | None = None
    status: Literal["active", "inactive"] | None = None


class GroupCreate(AdminRequest):
    code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=2_000)
    permission_codes: list[str] = Field(default_factory=list)


class GroupUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=2_000)
    permission_codes: list[str] | None = None
    status: Literal["active", "inactive"] | None = None


class GroupMembersUpdate(AdminRequest):
    user_ids: list[UUID]


class DatasourceScopeInput(AdminRequest):
    scope_value: str = Field(min_length=1, max_length=2_000)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    scope_type: str = Field(default="scope", min_length=1, max_length=32)
    settings: dict[str, Any] = Field(default_factory=dict)
    sync_schedule: dict[str, Any] = Field(default_factory=dict)


class DatasourceCreate(AdminRequest):
    provider: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=255)
    settings: dict[str, Any] = Field(default_factory=dict)
    credential_secret_ref: str | None = Field(default=None, min_length=1, max_length=512)
    scopes: list[DatasourceScopeInput] | None = None


class DatasourceUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    settings: dict[str, Any] | None = None
    credential_secret_ref: str | None = Field(default=None, min_length=1, max_length=512)
    status: Literal["draft", "active", "disabled", "error"] | None = None
    scopes: list[DatasourceScopeInput] | None = None


class DatasourceSyncRequest(AdminRequest):
    scope_id: int | None = Field(default=None, ge=1)


class DocumentLifecycleUpdate(AdminRequest):
    lifecycle_status: Literal[
        "active", "retired", "hidden", "unsupported", "failed"
    ]


class AccessRequestCreate(AdminRequest):
    requester_user_id: UUID
    resource_type: Literal["document", "group", "role"]
    resource_id: str = Field(min_length=1, max_length=512)
    access_type: str = Field(min_length=1, max_length=32)
    reason: str | None = Field(default=None, min_length=1, max_length=4_000)


class AccessRequestDecision(AdminRequest):
    decision: Literal["approved", "denied"]
    review_note: str | None = Field(default=None, min_length=1, max_length=4_000)


class AclPolicyCreate(AdminRequest):
    name: str = Field(min_length=1, max_length=255)
    resource_type: Literal["document"] = "document"
    resource_id: str = Field(min_length=1, max_length=512)
    allowed_principal_tokens: list[str] = Field(min_length=1)
    denied_principal_tokens: list[str] = Field(default_factory=list)


class AclPolicyUpdate(AdminRequest):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    allowed_principal_tokens: list[str] | None = None
    denied_principal_tokens: list[str] | None = None
    status: Literal["active", "inactive"] | None = None


def register_admin_error_handlers(app: FastAPI) -> None:
    """Translate service errors without leaking implementation details."""

    async def not_found(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc)},
        )

    async def conflict(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc)},
        )

    async def invalid(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": str(exc)},
        )

    async def forbidden(_: Request, exc: Exception) -> JSONResponse:
        detail = str(exc)
        unauthenticated = any(
            marker in detail
            for marker in (
                "authenticated request context",
                "development user ID",
                "request auth context",
            )
        )
        return JSONResponse(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
                if unauthenticated
                else status.HTTP_403_FORBIDDEN
            ),
            content={"detail": detail},
        )

    async def inactive(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
        )

    async def unavailable(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    async def integrity(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "the requested change conflicts with durable state"},
        )

    app.add_exception_handler(AdminNotFoundError, not_found)
    app.add_exception_handler(IdentityNotFoundError, not_found)
    app.add_exception_handler(AdminConflictError, conflict)
    app.add_exception_handler(AdminValidationError, invalid)
    app.add_exception_handler(AuthorizationError, forbidden)
    app.add_exception_handler(IdentityInactiveError, inactive)
    app.add_exception_handler(AdminExternalUnavailableError, unavailable)
    app.add_exception_handler(IntegrityError, integrity)


__all__ = [
    "AccessRequestCreate",
    "AccessRequestDecision",
    "AclPolicyCreate",
    "AclPolicyUpdate",
    "DatasourceCreate",
    "DatasourceScopeInput",
    "DatasourceSyncRequest",
    "DatasourceUpdate",
    "DocumentLifecycleUpdate",
    "GroupCreate",
    "GroupMembersUpdate",
    "GroupUpdate",
    "RoleCreate",
    "RoleUpdate",
    "SpaceUpdate",
    "UserCreate",
    "UserUpdate",
    "register_admin_error_handlers",
]
