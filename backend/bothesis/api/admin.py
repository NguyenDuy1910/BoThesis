"""Thin FastAPI boundary for the tenant Admin control plane."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.api import (
    AccessRequestCreate,
    AccessRequestDecision,
    AclPolicyCreate,
    AclPolicyUpdate,
    DatasourceCreate,
    DatasourceSyncRequest,
    DatasourceUpdate,
    DocumentLifecycleUpdate,
    GroupCreate,
    GroupMembersUpdate,
    GroupUpdate,
    RoleCreate,
    RoleUpdate,
    SpaceUpdate,
    UserCreate,
    UserUpdate,
)
from bothesis.db.engine import get_transactional_session
from bothesis.integrations import EnvironmentSecretResolver
from bothesis.services import (
    AccessRequestService,
    AclService,
    AdminDocumentService,
    AdminService,
    AuditService,
    AuthContext,
    DatasourceService,
    GroupService,
    RoleService,
    TenantService,
    UserService,
)
from bothesis.services.request_identity import resolve_auth_context

admin_router = APIRouter(prefix="/admin", tags=["admin"])


async def _admin_context(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_transactional_session)],
    x_bothesis_user_id: Annotated[
        str | None, Header(alias="X-Bothesis-User-Id")
    ] = None,
    x_bothesis_tenant_id: Annotated[
        str | None, Header(alias="X-Bothesis-Tenant-Id")
    ] = None,
) -> AuthContext:
    return await resolve_auth_context(
        request,
        session,
        claimed_user_id=x_bothesis_user_id,
        claimed_tenant_id=x_bothesis_tenant_id,
        allow_insecure_development_identity=bool(
            request.app.state.allow_insecure_development_identity
        ),
    )


Session = Annotated[AsyncSession, Depends(get_transactional_session)]
AdminContext = Annotated[AuthContext, Depends(_admin_context)]


@admin_router.get("/overview")
async def overview(session: Session, actor: AdminContext) -> dict[str, Any]:
    return await AdminService(session).overview(actor)


@admin_router.get("/spaces")
async def list_spaces(session: Session, actor: AdminContext) -> dict[str, Any]:
    return await TenantService(session).list_spaces(actor)


@admin_router.get("/spaces/{tenant_id}")
async def get_space(
    tenant_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await TenantService(session).get_space(actor, tenant_id)


@admin_router.patch("/spaces/{tenant_id}")
async def update_space(
    tenant_id: UUID,
    body: SpaceUpdate,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await TenantService(session).update_space(
        actor, tenant_id, **body.model_dump(exclude_unset=True)
    )


@admin_router.get("/users")
async def list_users(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    role_id: UUID | None = None,
    sort: str = "name",
    direction: str = "asc",
) -> dict[str, Any]:
    return await UserService(session).list_users(
        actor,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        role_id=role_id,
        sort=sort,
        direction=direction,
    )


@admin_router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await UserService(session).create_user(actor, **body.model_dump())


@admin_router.get("/users/{user_id}")
async def get_user(
    user_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await UserService(session).get_user(actor, user_id)


@admin_router.patch("/users/{user_id}")
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await UserService(session).update_user(
        actor, user_id, **body.model_dump(exclude_unset=True)
    )


@admin_router.get("/permissions")
async def list_permissions(session: Session, actor: AdminContext) -> dict[str, Any]:
    return await RoleService(session).list_permissions(actor)


@admin_router.get("/roles")
async def list_roles(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await RoleService(session).list_roles(
        actor,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@admin_router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await RoleService(session).create_role(actor, **body.model_dump())


@admin_router.get("/roles/{role_id}")
async def get_role(
    role_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await RoleService(session).get_role(actor, role_id)


@admin_router.patch("/roles/{role_id}")
async def update_role(
    role_id: UUID,
    body: RoleUpdate,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await RoleService(session).update_role(
        actor, role_id, **body.model_dump(exclude_unset=True)
    )


@admin_router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disable_role(
    role_id: UUID, session: Session, actor: AdminContext
) -> Response:
    await RoleService(session).disable_role(actor, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/groups")
async def list_groups(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await GroupService(session).list_groups(
        actor,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@admin_router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await GroupService(session).create_group(actor, **body.model_dump())


@admin_router.get("/groups/{group_id}")
async def get_group(
    group_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await GroupService(session).get_group(actor, group_id)


@admin_router.patch("/groups/{group_id}")
async def update_group(
    group_id: UUID,
    body: GroupUpdate,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await GroupService(session).update_group(
        actor, group_id, **body.model_dump(exclude_unset=True)
    )


@admin_router.put("/groups/{group_id}/members")
async def replace_group_members(
    group_id: UUID,
    body: GroupMembersUpdate,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await GroupService(session).replace_members(
        actor, group_id, body.user_ids
    )


@admin_router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: UUID, session: Session, actor: AdminContext
) -> Response:
    await GroupService(session).delete_group(actor, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/datasources/capabilities")
async def datasource_capabilities(
    session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await _datasources(session).capabilities(actor)


@admin_router.get("/datasources")
async def list_datasources(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    provider: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await _datasources(session).list_datasources(
        actor,
        page=page,
        page_size=page_size,
        search=search,
        provider=provider,
        status=status_filter,
    )


@admin_router.post("/datasources", status_code=status.HTTP_201_CREATED)
async def create_datasource(
    body: DatasourceCreate, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await _datasources(session).create_datasource(
        actor, **body.model_dump()
    )


@admin_router.put("/datasources/{connector_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_datasource_file(
    connector_id: int,
    request: Request,
    session: Session,
    actor: AdminContext,
    x_bothesis_file_name: Annotated[
        str | None, Header(alias="X-Bothesis-File-Name")
    ] = None,
) -> dict[str, Any]:
    return await _datasources(session).upload_file(
        actor,
        connector_id,
        file_name=unquote(x_bothesis_file_name or ""),
        content=request.stream(),
    )


@admin_router.get("/datasources/{connector_id}")
async def get_datasource(
    connector_id: int, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await _datasources(session).get_datasource(actor, connector_id)


@admin_router.patch("/datasources/{connector_id}")
async def update_datasource(
    connector_id: int,
    body: DatasourceUpdate,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await _datasources(session).update_datasource(
        actor, connector_id, **body.model_dump(exclude_unset=True)
    )


@admin_router.delete(
    "/datasources/{connector_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_datasource(
    connector_id: int, session: Session, actor: AdminContext
) -> Response:
    await _datasources(session).delete_datasource(actor, connector_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post("/datasources/{connector_id}/validate")
async def validate_datasource(
    connector_id: int, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await _datasources(session).validate_datasource(actor, connector_id)


@admin_router.post(
    "/datasources/{connector_id}/sync", status_code=status.HTTP_202_ACCEPTED
)
async def sync_datasource(
    connector_id: int,
    body: DatasourceSyncRequest,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await _datasources(session).trigger_sync(
        actor, connector_id, scope_id=body.scope_id
    )


@admin_router.get("/ingestion/jobs")
async def list_ingestion_jobs(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    connector_id: int | None = None,
) -> dict[str, Any]:
    return await _datasources(session).list_sync_runs(
        actor,
        page=page,
        page_size=page_size,
        status=status_filter,
        connector_id=connector_id,
    )


@admin_router.get("/ingestion/jobs/{run_id}")
async def get_ingestion_job(
    run_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await _datasources(session).get_sync_run(actor, run_id)


@admin_router.post("/ingestion/jobs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_ingestion_job(
    run_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await _datasources(session).retry_sync(actor, run_id)


@admin_router.post("/ingestion/jobs/{run_id}/cancel")
async def cancel_ingestion_job(
    run_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await _datasources(session).cancel_sync(actor, run_id)


@admin_router.get("/documents")
async def list_documents(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    lifecycle_status: str | None = None,
    indexing_status: str | None = None,
    connector_id: int | None = None,
    sort: str = "updated_at",
    direction: str = "desc",
) -> dict[str, Any]:
    return await AdminDocumentService(session).list_documents(
        actor,
        page=page,
        page_size=page_size,
        search=search,
        lifecycle_status=lifecycle_status,
        indexing_status=indexing_status,
        connector_id=connector_id,
        sort=sort,
        direction=direction,
    )


@admin_router.get("/documents/{document_id}")
async def get_document(
    document_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await AdminDocumentService(session).get_document(actor, document_id)


@admin_router.patch("/documents/{document_id}")
async def update_document(
    document_id: UUID,
    body: DocumentLifecycleUpdate,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await AdminDocumentService(session).update_lifecycle(
        actor, document_id, lifecycle_status=body.lifecycle_status
    )


@admin_router.post("/documents/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_document(
    document_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await AdminDocumentService(session).retry_document(actor, document_id)


@admin_router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID, session: Session, actor: AdminContext
) -> Response:
    await AdminDocumentService(session).delete_document(actor, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/access-requests")
async def list_access_requests(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    return await AccessRequestService(session).list_requests(
        actor,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        resource_type=resource_type,
    )


@admin_router.post("/access-requests", status_code=status.HTTP_201_CREATED)
async def create_access_request(
    body: AccessRequestCreate, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await AccessRequestService(session).create_request(
        actor, **body.model_dump()
    )


@admin_router.get("/access-requests/{request_id}")
async def get_access_request(
    request_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await AccessRequestService(session).get_request(actor, request_id)


@admin_router.post("/access-requests/{request_id}/decision")
async def decide_access_request(
    request_id: UUID,
    body: AccessRequestDecision,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await AccessRequestService(session).decide_request(
        actor, request_id, **body.model_dump()
    )


@admin_router.get("/acl-policies")
async def list_acl_policies(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await AclService(session).list_policies(
        actor,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@admin_router.post("/acl-policies", status_code=status.HTTP_201_CREATED)
async def create_acl_policy(
    body: AclPolicyCreate, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await AclService(session).create_policy(actor, **body.model_dump())


@admin_router.get("/acl-policies/{policy_id}")
async def get_acl_policy(
    policy_id: UUID, session: Session, actor: AdminContext
) -> dict[str, Any]:
    return await AclService(session).get_policy(actor, policy_id)


@admin_router.patch("/acl-policies/{policy_id}")
async def update_acl_policy(
    policy_id: UUID,
    body: AclPolicyUpdate,
    session: Session,
    actor: AdminContext,
) -> dict[str, Any]:
    return await AclService(session).update_policy(
        actor, policy_id, **body.model_dump(exclude_unset=True)
    )


@admin_router.delete("/acl-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_acl_policy(
    policy_id: UUID, session: Session, actor: AdminContext
) -> Response:
    await AclService(session).delete_policy(actor, policy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/audit-logs")
async def list_audit_logs(
    session: Session,
    actor: AdminContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    return await AuditService(session).list_events(
        actor,
        page=page,
        page_size=page_size,
        search=search,
        action=action,
        resource_type=resource_type,
    )


def _datasources(session: AsyncSession) -> DatasourceService:
    return DatasourceService(
        session,
        secret_resolver=EnvironmentSecretResolver(),
    )


__all__ = ["admin_router"]
