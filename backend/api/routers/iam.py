"""Workspace identity and access-management resources."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from api.deps import Caller, WorkspaceControlPlane
from api.routers import (
    Group,
    GroupCreate,
    GroupMembersUpdate,
    GroupPage,
    GroupUpdate,
    Permission,
    PermissionPage,
    Role,
    RoleCreate,
    RolePage,
    RoleUpdate,
    User,
    UserCreate,
    UserPage,
    UserUpdate,
)
from api.routers._mapping import role_payload, user_payload

router = APIRouter(tags=["iam"])


@router.get("/users", response_model=UserPage)
async def list_users(
    caller: Caller,
    control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> UserPage:
    value = await control_plane.list_users(
        caller, page=page, page_size=page_size, search=search
    )
    return UserPage(
        items=[user_payload(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.post("/users", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, caller: Caller, control_plane: WorkspaceControlPlane
) -> User:
    return User.model_validate(
        user_payload(await control_plane.create_user(caller, body.model_dump()))
    )


@router.get("/users/{user_id}", response_model=User)
async def get_user(
    user_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane
) -> User:
    return User.model_validate(
        user_payload(await control_plane.get_user(caller, user_id))
    )


@router.patch("/users/{user_id}", response_model=User)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> User:
    return User.model_validate(
        user_payload(
            await control_plane.update_user(
                caller, user_id, body.model_dump(exclude_unset=True)
            )
        )
    )


@router.get("/roles", response_model=RolePage)
async def list_roles(
    caller: Caller,
    control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> RolePage:
    value = await control_plane.list_roles(
        caller, page=page, page_size=page_size, search=search
    )
    return RolePage(
        items=[role_payload(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.post("/roles", response_model=Role, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate, caller: Caller, control_plane: WorkspaceControlPlane
) -> Role:
    return Role.model_validate(
        role_payload(await control_plane.create_role(caller, body.model_dump()))
    )


@router.get("/roles/{role_id}", response_model=Role)
async def get_role(
    role_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane
) -> Role:
    return Role.model_validate(
        role_payload(await control_plane.get_role(caller, role_id))
    )


@router.patch("/roles/{role_id}", response_model=Role)
async def update_role(
    role_id: UUID,
    body: RoleUpdate,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Role:
    return Role.model_validate(
        role_payload(
            await control_plane.update_role(
                caller, role_id, body.model_dump(exclude_unset=True)
            )
        )
    )


@router.get("/groups", response_model=GroupPage)
async def list_groups(
    caller: Caller,
    control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> GroupPage:
    value = await control_plane.list_groups(
        caller, page=page, page_size=page_size, search=search
    )
    return GroupPage(
        items=value.get("items", []),
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.post("/groups", response_model=Group, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate, caller: Caller, control_plane: WorkspaceControlPlane
) -> Group:
    return Group.model_validate(
        await control_plane.create_group(caller, body.model_dump())
    )


@router.get("/groups/{group_id}", response_model=Group)
async def get_group(
    group_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane
) -> Group:
    return Group.model_validate(await control_plane.get_group(caller, group_id))


@router.patch("/groups/{group_id}", response_model=Group)
async def update_group(
    group_id: UUID,
    body: GroupUpdate,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Group:
    return Group.model_validate(
        await control_plane.update_group(
            caller, group_id, body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane
) -> Response:
    await control_plane.delete_group(caller, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/groups/{group_id}/members", response_model=Group)
async def replace_group_members(
    group_id: UUID,
    body: GroupMembersUpdate,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Group:
    return Group.model_validate(
        await control_plane.replace_group_members(caller, group_id, body.user_ids)
    )


@router.get("/permissions", response_model=PermissionPage)
async def list_permissions(
    caller: Caller, control_plane: WorkspaceControlPlane
) -> PermissionPage:
    value = await control_plane.list_permissions(caller)
    return PermissionPage(
        items=[Permission.model_validate(item) for item in value.get("items", [])],
        total=value.get("total", 0),
    )


__all__ = ["router"]
