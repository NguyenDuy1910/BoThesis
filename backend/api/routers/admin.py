"""Tenant administration routes for the Admin control plane."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from api.deps import AdminConsole, Caller
from api.routers import (
    AccessRequestCreate,
    AccessRequestDecision,
    AdminRoleCreate,
    AdminRoleUpdate,
    CollectionAccessGrant,
    CollectionCreate,
    CollectionUpdate,
    GroupCreate,
    GroupMembersUpdate,
    GroupUpdate,
    IngestionSourceCreate,
    IngestionSourceUpdate,
    IntegrationConnectionCreate,
    IntegrationConnectionUpdate,
    ItemStatusUpdate,
    ScheduleInput,
    SpaceUpdate,
    UserCreate,
    UserUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
async def admin_overview(caller: Caller, admin: AdminConsole) -> dict[str, Any]:
    return await admin.overview(caller)


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
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    role_id: UUID | None = None,
    sort: str = "name",
    direction: str = "asc",
) -> dict[str, Any]:
    return await admin.list_users(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
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


@router.get("/connectors/capabilities")
async def admin_connector_capabilities(caller: Caller, admin: AdminConsole) -> dict[str, Any]:
    return await admin.connector_capabilities(caller)


@router.get("/integration-connections")
async def admin_list_integration_connections(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    connector_key: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await admin.list_integration_connections(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        connector_key=connector_key,
        status=status_filter,
    )


@router.post("/integration-connections", status_code=status.HTTP_201_CREATED)
async def admin_create_integration_connection(
    body: IntegrationConnectionCreate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.create_integration_connection(caller, body.model_dump())


@router.get("/integration-connections/{integration_connection_id}")
async def admin_get_integration_connection(
    integration_connection_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_integration_connection(caller, integration_connection_id)


@router.patch("/integration-connections/{integration_connection_id}")
async def admin_update_integration_connection(
    integration_connection_id: UUID,
    body: IntegrationConnectionUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_integration_connection(
        caller, integration_connection_id, body.model_dump(exclude_unset=True)
    )


@router.delete(
    "/integration-connections/{integration_connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_integration_connection(
    integration_connection_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> Response:
    await admin.delete_integration_connection(caller, integration_connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/integration-connections/{integration_connection_id}/validate")
async def admin_validate_integration_connection(
    integration_connection_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.validate_integration_connection(caller, integration_connection_id)


@router.get("/ingestion-sources")
async def admin_list_ingestion_sources(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    integration_connection_id: UUID | None = None,
    target_item_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await admin.list_ingestion_sources(
        caller,
        page=page,
        page_size=page_size,
        integration_connection_id=integration_connection_id,
        target_item_id=target_item_id,
        status=status_filter,
    )


@router.post(
    "/integration-connections/{integration_connection_id}/sources",
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_ingestion_source(
    integration_connection_id: UUID,
    body: IngestionSourceCreate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.create_ingestion_source(
        caller, integration_connection_id, body.model_dump()
    )


@router.get("/ingestion-sources/{source_id}")
async def admin_get_ingestion_source(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_ingestion_source(caller, source_id)


@router.patch("/ingestion-sources/{source_id}")
async def admin_update_ingestion_source(
    source_id: UUID,
    body: IngestionSourceUpdate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.update_ingestion_source(
        caller, source_id, body.model_dump(exclude_unset=True)
    )


@router.delete(
    "/ingestion-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def admin_delete_ingestion_source(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> Response:
    await admin.delete_ingestion_source(caller, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/ingestion-sources/{source_id}/ingest", status_code=status.HTTP_202_ACCEPTED
)
async def admin_ingest_source(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.ingest_source(caller, source_id)


@router.get("/ingestion-sources/{source_id}/workflows")
async def admin_list_source_workflows(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await admin.list_source_workflows(
        caller,
        source_id,
        page=page,
        page_size=page_size,
        status=status_filter,
    )


@router.get("/ingestion-sources/{source_id}/workflows/{workflow_id}")
async def admin_get_source_workflow(
    source_id: UUID,
    workflow_id: str,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_source_workflow(
        caller, source_id, workflow_id
    )


@router.get("/ingestion-sources/{source_id}/status")
async def admin_get_source_status(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_source_status(caller, source_id)


@router.get("/ingestion-sources/{source_id}/schedule")
async def admin_get_source_schedule(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_source_schedule(caller, source_id)


@router.put("/ingestion-sources/{source_id}/schedule")
async def admin_set_source_schedule(
    source_id: UUID,
    body: ScheduleInput,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.set_source_schedule(
        caller, source_id, body.model_dump()
    )


@router.delete(
    "/ingestion-sources/{source_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_source_schedule(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> Response:
    await admin.delete_source_schedule(caller, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/ingestion-sources/{source_id}/schedule/pause")
async def admin_pause_source_schedule(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.pause_source_schedule(caller, source_id)


@router.post("/ingestion-sources/{source_id}/schedule/resume")
async def admin_resume_source_schedule(
    source_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.resume_source_schedule(caller, source_id)


@router.get("/ingestion/jobs")
async def admin_list_ingestion_jobs(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    integration_connection_id: UUID | None = None,
    source_id: UUID | None = None,
) -> dict[str, Any]:
    return await admin.list_ingestion_jobs(
        caller,
        page=page,
        page_size=page_size,
        status=status_filter,
        integration_connection_id=integration_connection_id,
        source_id=source_id,
    )


@router.get("/ingestion/jobs/{workflow_id}")
async def admin_get_ingestion_job(
    workflow_id: str,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_ingestion_job(caller, workflow_id)


@router.post(
    "/ingestion/jobs/{workflow_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
)
async def admin_retry_ingestion_job(
    workflow_id: str,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.retry_ingestion_job(caller, workflow_id)


@router.post("/ingestion/jobs/{workflow_id}/cancel")
async def admin_cancel_ingestion_job(
    workflow_id: str,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.cancel_ingestion_job(caller, workflow_id)


@router.get("/items")
async def admin_list_items(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    item_type: str | None = None,
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


@router.get("/access-requests")
async def admin_list_access_requests(
    caller: Caller,
    admin: AdminConsole,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await admin.list_access_requests(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@router.post("/access-requests", status_code=status.HTTP_201_CREATED)
async def admin_create_access_request(
    body: AccessRequestCreate,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.create_access_request(caller, body.model_dump())


@router.get("/access-requests/{request_id}")
async def admin_get_access_request(
    request_id: UUID,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.get_access_request(caller, request_id)


@router.post("/access-requests/{request_id}/decision")
async def admin_decide_access_request(
    request_id: UUID,
    body: AccessRequestDecision,
    caller: Caller,
    admin: AdminConsole,
) -> dict[str, Any]:
    return await admin.decide_access_request(
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
    body: CollectionAccessGrant,
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
