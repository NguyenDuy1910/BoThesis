"""Workspace resources and workspace overview projection."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from uuid import UUID

from api.deps import Caller, WorkspaceControlPlane
from api.routers import Workspace, WorkspaceOverview, WorkspacePage, WorkspaceUpdate
from api.routers._mapping import workspace_payload

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=WorkspacePage)
async def list_workspaces(
    caller: Caller, control_plane: WorkspaceControlPlane
) -> WorkspacePage:
    value = await control_plane.list_workspaces(caller)
    items = [workspace_payload(item) for item in value.get("items", [])]
    return WorkspacePage(
        items=items,
        page=value.get("page", 1),
        page_size=value.get("page_size", max(1, len(items))),
        total=value.get("total", len(items)),
    )


@router.get("/{workspace_id}", response_model=Workspace)
async def get_workspace(
    workspace_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane
) -> Workspace:
    return Workspace.model_validate(
        workspace_payload(await control_plane.get_workspace(caller, workspace_id))
    )


@router.patch("/{workspace_id}", response_model=Workspace)
async def update_workspace(
    workspace_id: UUID,
    body: WorkspaceUpdate,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Workspace:
    return Workspace.model_validate(
        workspace_payload(
            await control_plane.update_workspace(
                caller, workspace_id, body.model_dump(exclude_unset=True)
            )
        )
    )


@router.get("/{workspace_id}/overview", response_model=WorkspaceOverview)
async def get_workspace_overview(
    workspace_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane
) -> WorkspaceOverview:
    value = await control_plane.workspace_overview(caller)
    workspace = value.get("workspace") or await control_plane.get_workspace(
        caller, workspace_id
    )
    return WorkspaceOverview(
        workspace=Workspace.model_validate(workspace_payload(workspace)),
        metrics=value.get("metrics", {}),
        attention=value.get("attention", {}),
        recent_activity=value.get("recent_activity", []),
        generated_at=value.get("generated_at") or datetime.now(),
    )


__all__ = ["router"]
