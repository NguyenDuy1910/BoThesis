"""Tenant administration routes for the Admin control plane."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from api.deps import AdminConsole, Caller, Health
from api.routers import (
    AdminRoleCreate,
    AdminRoleUpdate,
    ApprovalRequestCreate,
    ApprovalRequestUpdate,
    CollectionRoleGrant,
    CollectionCreate,
    CollectionUpdate,
    GroupCreate,
    GroupMembersUpdate,
    GroupUpdate,
    ItemStatusUpdate,
    SpaceUpdate,
    UserCreate,
    UserUpdate,
)
from bothesis.services import (
    PLATFORM_HEALTH_READ_PERMISSION,
    require_platform_permission,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
async def admin_overview(caller: Caller, admin: AdminConsole) -> dict[str, Any]:
    return await admin.overview(caller)


@router.get("/platform/overview")
async def platform_overview(caller: Caller, admin: AdminConsole) -> dict[str, Any]:
    return await admin.platform_overview(caller)


@router.get("/platform/workspaces")
async def platform_list_workspaces(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return await admin.list_platform_workspaces(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        status=status,
    )


@router.get("/platform/users")
async def platform_list_users(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status: bool | None = None,
) -> dict[str, Any]:
    return await admin.list_platform_users(
        caller, page=page, page_size=page_size, search=search, status=status
    )


@router.get("/platform/audit")
async def platform_list_audit(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> dict[str, Any]:
    return await admin.list_platform_audit_logs(
        caller, page=page, page_size=page_size, search=search
    )


@router.get("/platform/health")
async def platform_health(caller: Caller, health: Health) -> dict[str, Any]:
    require_platform_permission(caller, PLATFORM_HEALTH_READ_PERMISSION)
    return (await health.check()).model_dump(mode="json")


@router.get("/spaces")
async def admin_list_spaces(caller: Caller, admin: AdminConsole) -> dict[str, Any]:
    return await admin.list_spaces(caller)


@router.get("/spaces/{tenant_id}")
async def admin_get_space(
    tenant_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_space(caller, tenant_id)


@router.patch("/spaces/{tenant_id}")
async def admin_update_space(
    tenant_id: UUID,
    body: SpaceUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_space(
        caller, tenant_id, body.model_dump(exclude_unset=True)
    )


@router.get("/users")
async def admin_list_users(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status: bool | None = None,
    role_id: UUID | None = None,
    sort: str = "name",
    direction: str = "asc",
) -> dict[str, Any]:
    return await admin.list_users(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        role_id=role_id,
        sort=sort,
        direction=direction,
    )


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    body: UserCreate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.create_user(caller, body.model_dump())


@router.get("/users/{user_id}")
async def admin_get_user(
    user_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_user(caller, user_id)


@router.patch("/users/{user_id}")
async def admin_update_user(
    user_id: UUID,
    body: UserUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_user(
        caller, user_id, body.model_dump(exclude_unset=True)
    )


@router.get("/permissions")
async def admin_list_permissions(caller: Caller, admin: AdminConsole) -> dict[str, Any]:
    return await admin.list_permissions(caller)


@router.get("/roles")
async def admin_list_roles(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await admin.list_roles(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def admin_create_role(
    body: AdminRoleCreate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.create_role(caller, body.model_dump())


@router.get("/roles/{role_id}")
async def admin_get_role(
    role_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_role(caller, role_id)


@router.patch("/roles/{role_id}")
async def admin_update_role(
    role_id: UUID,
    body: AdminRoleUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_role(
        caller, role_id, body.model_dump(exclude_unset=True)
    )


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_disable_role(role_id: UUID, caller: Caller, admin: AdminConsole) -> Response:
    await admin.disable_role(caller, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/groups")
async def admin_list_groups(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await admin.list_groups(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def admin_create_group(
    body: GroupCreate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.create_group(caller, body.model_dump())


@router.get("/groups/{group_id}")
async def admin_get_group(
    group_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_group(caller, group_id)


@router.patch("/groups/{group_id}")
async def admin_update_group(
    group_id: UUID,
    body: GroupUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_group(
        caller, group_id, body.model_dump(exclude_unset=True)
    )


@router.put("/groups/{group_id}/members")
async def admin_replace_group_members(
    group_id: UUID,
    body: GroupMembersUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.replace_group_members(
        caller, group_id, body.user_ids
    )


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_group(
    group_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> Response:
    await admin.delete_group(caller, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items")
async def admin_list_items(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    item_type: str | None = None,
    parent_item_id: UUID | None = None,
    ingestion_source_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
    sort: str = "updated_at",
    direction: str = "desc",
) -> dict[str, Any]:
    return await admin.list_items(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        item_type=item_type,
        parent_item_id=parent_item_id,
        ingestion_source_id=ingestion_source_id,
        created_by_user_id=created_by_user_id,
        sort=sort,
        direction=direction,
    )


@router.post("/collections", status_code=status.HTTP_201_CREATED)
async def admin_create_collection(
    body: CollectionCreate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.create_collection(caller, body.model_dump())


@router.patch("/collections/{item_id}")
async def admin_update_collection(
    item_id: UUID,
    body: CollectionUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_collection(
        caller,
        item_id,
        body.model_dump(exclude_unset=True),
    )


@router.get("/items/{item_id}")
async def admin_get_item(
    item_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_item(caller, item_id)


@router.patch("/items/{item_id}")
async def admin_update_item(
    item_id: UUID,
    body: ItemStatusUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_item(
        caller, item_id, body.status
    )


@router.post(
    "/items/{item_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
)
async def admin_retry_item(
    item_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.retry_item(caller, item_id)


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_item(
    item_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> Response:
    await admin.delete_item(caller, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/approval-requests")
async def admin_list_approval_requests(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    request_type: Annotated[str | None, Query(alias="request_type")] = None,
) -> dict[str, Any]:
    return await admin.list_approval_requests(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        request_type=request_type,
    )


@router.post("/approval-requests", status_code=status.HTTP_201_CREATED)
async def admin_create_approval_request(
    body: ApprovalRequestCreate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.create_approval_request(caller, body.model_dump())


@router.get("/approval-requests/{request_id}")
async def admin_get_approval_request(
    request_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_approval_request(caller, request_id)


@router.patch("/approval-requests/{request_id}")
async def admin_update_approval_request(
    request_id: UUID,
    body: ApprovalRequestUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_approval_request(
        caller, request_id, body.model_dump()
    )


@router.get("/collections/{item_id}/access")
async def admin_list_collection_access(
    item_id: UUID,
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict[str, Any]:
    return await admin.list_collection_access(
        caller, item_id, page=page, page_size=page_size
    )


@router.put("/collections/{item_id}/access")
async def admin_grant_collection_access(
    item_id: UUID,
    body: CollectionRoleGrant,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.grant_collection_access(
        caller, item_id, body.model_dump()
    )


@router.delete(
    "/collections/{item_id}/access/{principal_type}/{principal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_revoke_collection_access(
    item_id: UUID,
    principal_type: Literal["user", "group"],
    principal_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> Response:
    await admin.revoke_collection_access(
        caller,
        item_id,
        principal_type=principal_type,
        principal_id=principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audit-logs")
async def admin_list_audit_logs(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    return await admin.list_audit_logs(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        action=action,
        resource_type=resource_type,
    )
