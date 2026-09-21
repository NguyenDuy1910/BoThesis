"""Platform-scope resources."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from api.deps import Caller, Health, WorkspaceControlPlane
from api.routers import (
    AuditLog,
    AuditLogPage,
    PlatformOverview,
    UserPage,
    WorkspacePage,
)
from api.routers._mapping import user_payload, workspace_payload

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/overview", response_model=PlatformOverview)
async def get_platform_overview(
    caller: Caller, control_plane: WorkspaceControlPlane
) -> PlatformOverview:
    return PlatformOverview.model_validate(
        await control_plane.platform_overview(caller)
    )


@router.get("/health")
async def get_platform_health(health: Health) -> dict[str, object]:
    return (await health.check()).model_dump(mode="json")


@router.get("/workspaces", response_model=WorkspacePage)
async def list_platform_workspaces(
    caller: Caller,
    control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status: str | None = None,
) -> WorkspacePage:
    value = await control_plane.list_platform_workspaces(
        caller, page=page, page_size=page_size, search=search, status=status
    )
    return WorkspacePage(
        items=[workspace_payload(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.get("/users", response_model=UserPage)
async def list_platform_users(
    caller: Caller,
    control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status: bool | None = None,
) -> UserPage:
    value = await control_plane.list_platform_users(
        caller, page=page, page_size=page_size, search=search, status=status
    )
    return UserPage(
        items=[user_payload(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.get("/audit-logs", response_model=AuditLogPage)
async def list_platform_audit_logs(
    caller: Caller,
    control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> AuditLogPage:
    value = await control_plane.list_platform_audit_logs(
        caller, page=page, page_size=page_size, search=search
    )
    return AuditLogPage(
        items=[AuditLog.model_validate(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


__all__ = ["router"]
