"""Resource-oriented routes backed by existing domain application services."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Query, Response, status

from api.deps import WorkspaceControlPlane, Caller, Documents, Health, Integrations, KnowledgeView
from api.routers import (
    Collection,
    CollectionAccess,
    CollectionAccessPage,
    CollectionAccessUpdate,
    CollectionPage,
    CollectionUpdate,
    CollectionCreate,
    Document,
    RoleCreate,
    RoleUpdate,
    ApprovalRequestCreate,
    ApprovalRequestUpdate,
    KnowledgeHomeResponse,
    DocumentStatus,
    ApprovalRequest,
    ApprovalRequestPage,
    AuditLog,
    AuditLogPage,
    Connection,
    ConnectionAuthorization,
    ConnectionAuthorizationCreate,
    ConnectionCreate,
    ConnectionPage,
    ConnectionUpdate,
    ConnectionValidation,
    Group,
    GroupPage,
    GroupCreate,
    GroupUpdate,
    GroupMembersUpdate,
    Ingestion,
    IngestionPage,
    Permission,
    PermissionPage,
    PlatformOverview,
    ProviderCatalog,
    ProviderResourcePage,
    RolePage,
    Role,
    Source,
    SourceCreate,
    SourcePage,
    SourceStatus,
    SourceUpdate,
    Schedule,
    SchedulePut,
    SchedulePatch,
    User,
    UserCreate,
    UserPage,
    UserUpdate,
    Workspace,
    WorkspaceOverview,
    WorkspacePage,
    WorkspaceUpdate,
)
from pydantic import BaseModel
from bothesis.services import ControlPlaneNotFoundError


class KnowledgeDocumentViewer(BaseModel):
    document_id: UUID
    title: str
    content_type: str
    status: DocumentStatus
    document_url: str | None = None
    external_url: str | None = None
    elements: list[dict[str, Any]]


class KnowledgeDocumentCitation(BaseModel):
    document_id: UUID
    chunk_id: str
    title: str
    content_type: str
    citation: dict[str, Any]

router = APIRouter(tags=["collections", "workspaces", "iam", "governance", "platform"])


def _connection_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value["id"], "connector_key": value.get("connector_key", ""),
        "display_name": value.get("display_name", ""),
        "owner_type": "workspace" if value.get("owner_type") == "tenant" else value.get("owner_type", "user"),
        "owner_user_id": value.get("owner_user_id"), "status": value.get("status", "error"),
        "source_count": value.get("source_count", 0), "config": value.get("config", {}),
        "created_at": value["created_at"], "updated_at": value["updated_at"],
    }


def _source_payload(value: dict[str, Any]) -> dict[str, Any]:
    connection = value.get("integration_connection") or {}
    return {
        "id": value["id"], "connection_id": value.get("integration_connection_id"),
        "collection_id": value.get("target_item_id"), "display_name": value.get("display_name"),
        "resource_type": value.get("resource_type"), "external_resource_id": value.get("external_resource_id"),
        "sync_mode": value.get("sync_mode", "manual"), "status": value.get("status", "failed"),
        "schedule": value.get("schedule"),
    }


def _ingestion_id(workflow_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"bothesis:ingestion:{workflow_id}")


def _ingestion_payload(value: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(value.get("id") or value.get("workflow_id"))
    return {
        "id": _ingestion_id(raw_id),
        "source_id": value.get("source_id"),
        "connection_id": value.get("integration_connection_id"),
        "status": value.get("status", "pending"),
        "trigger_type": value.get("trigger_type", "manual"),
        "progress": value.get("progress"),
        "started_at": value.get("started_at"), "finished_at": value.get("finished_at"),
        "created_at": value.get("started_at") or datetime.now().isoformat(),
        "updated_at": value.get("finished_at") or value.get("started_at") or datetime.now().isoformat(),
    }


def _workspace_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value["id"], "code": value.get("code", ""), "name": value.get("name", ""),
        "status": value.get("status", "active"), "visibility": value.get("visibility"),
        "settings": value.get("settings", {}),
    }


def _user_payload(value: dict[str, Any]) -> dict[str, Any]:
    status_value = value.get("status", "active")
    if isinstance(status_value, bool):
        status_value = "active" if status_value else "inactive"
    membership = value.get("membership") or {}
    return {"id": value["id"], "email": value["email"], "display_name": value.get("display_name"), "status": status_value, "roles": membership.get("roles", []), "groups": value.get("groups", [])}


def _role_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {"id": value["id"], "code": value.get("code", ""), "display_name": value.get("display_name", ""), "status": value.get("status", "active"), "permission_codes": value.get("permission_codes", [])}


def _approval_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "created_at": value.get("created_at") or datetime.now().isoformat()}


@router.get("/collections", response_model=CollectionPage)
async def list_collections(
    caller: Caller, control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> CollectionPage:
    return CollectionPage.model_validate(await control_plane.list_collections(
        caller, page=page, page_size=page_size, search=search
    ))


@router.post("/collections", response_model=Collection, status_code=status.HTTP_201_CREATED)
async def create_collection(body: CollectionCreate, caller: Caller, control_plane: WorkspaceControlPlane) -> Collection:
    values = {
        "title": body.title,
        "parent_item_id": body.parent_collection_id,
        "inherit_access": body.inherit_access,
        "metadata": {"description": body.description} if body.description is not None else {},
    }
    return Collection.model_validate(await control_plane.create_collection_contract(caller, values))


@router.put("/collections/personal", response_model=Collection)
async def ensure_personal_collection(caller: Caller, documents: Documents, control_plane: WorkspaceControlPlane) -> Collection:
    value = await documents.ensure_personal_collection(caller)
    return Collection.model_validate(await control_plane.get_collection(caller, UUID(str(value["id"]))))


@router.get("/collections/{collection_id}", response_model=Collection)
async def get_collection(collection_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> Collection:
    return Collection.model_validate(await control_plane.get_collection(caller, collection_id))


@router.patch("/collections/{collection_id}", response_model=Collection)
async def update_collection(collection_id: UUID, body: CollectionUpdate, caller: Caller, control_plane: WorkspaceControlPlane) -> Collection:
    return Collection.model_validate(await control_plane.update_collection_contract(
        caller, collection_id, body.model_dump(exclude_unset=True)
    ))


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(collection_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> Response:
    await control_plane.delete_collection(caller, collection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/collections/{collection_id}/access", response_model=CollectionAccessPage)
async def list_collection_access(
    collection_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CollectionAccessPage:
    value = await control_plane.list_collection_access(caller, collection_id, page=page, page_size=page_size)
    return CollectionAccessPage.model_validate(value)


@router.put("/collections/{collection_id}/access/{principal_type}/{principal_id}", response_model=CollectionAccess)
async def put_collection_access(
    collection_id: UUID, principal_type: Literal["user", "group"], principal_id: UUID,
    body: CollectionAccessUpdate, caller: Caller, control_plane: WorkspaceControlPlane,
) -> CollectionAccess:
    value = await control_plane.grant_collection_access(caller, collection_id, {
        "principal_type": principal_type, "principal_id": principal_id,
        "role_code": f"collection_{body.role}",
    })
    return CollectionAccess.model_validate({
        "collection_id": collection_id,
        "principal_type": principal_type,
        "principal_id": principal_id,
        "role": body.role,
        "created_at": value.get("created_at"),
        "updated_at": value.get("updated_at"),
    })


@router.delete("/collections/{collection_id}/access/{principal_type}/{principal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection_access(
    collection_id: UUID, principal_type: Literal["user", "group"], principal_id: UUID,
    caller: Caller, control_plane: WorkspaceControlPlane,
) -> Response:
    await control_plane.revoke_collection_access(caller, collection_id, principal_type=principal_type, principal_id=principal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/knowledge/home", response_model=KnowledgeHomeResponse, operation_id="getKnowledgeHome")
async def knowledge_home(caller: Caller, knowledge: KnowledgeView) -> KnowledgeHomeResponse:
    value = await knowledge.get_workspace_home(caller)
    return KnowledgeHomeResponse(
        collections=[Collection.model_validate(item) for item in value.get("items", [])],
        recent_documents=[Document.model_validate(item) for item in value.get("recent_documents", [])],
        personal_collection_id=value.get("personal_collection_id"),
    )


@router.get("/knowledge/documents/{document_id}", operation_id="getKnowledgeDocument")
async def knowledge_document(document_id: UUID, caller: Caller, knowledge: KnowledgeView, chunk: str | None = None) -> KnowledgeDocumentViewer:
    value = await knowledge.get_item(caller, item_id=str(document_id), chunk_id=chunk)
    value["document_id"] = value.pop("item_id")
    value["status"] = {"pending": "pending_content", "ready": "available", "processing": "available"}.get(value["status"], value["status"])
    return KnowledgeDocumentViewer.model_validate(value)


@router.get("/knowledge/documents/{document_id}/citations/{chunk_id}", operation_id="getKnowledgeDocumentCitation")
async def knowledge_citation(document_id: UUID, chunk_id: str, caller: Caller, knowledge: KnowledgeView) -> KnowledgeDocumentCitation:
    value = await knowledge.get_citation(caller, item_id=str(document_id), chunk_id=chunk_id)
    value["document_id"] = value.pop("item_id")
    return KnowledgeDocumentCitation.model_validate(value)


# Connections and sources -------------------------------------------------
@router.get("/connections/providers", response_model=ProviderCatalog)
async def list_connection_providers(caller: Caller, integrations: Integrations) -> ProviderCatalog:
    value = await integrations.connector_capabilities(caller)
    return ProviderCatalog(items=value.get("connectors", value.get("items", [])))


@router.get("/connections", response_model=ConnectionPage)
async def list_connections(caller: Caller, integrations: Integrations, page: int = 1, page_size: int = 20, search: str | None = None) -> ConnectionPage:
    value = await integrations.list_connections(caller, page=page, page_size=page_size, search=search)
    return ConnectionPage(items=[_connection_payload(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.post("/connections", response_model=Connection, status_code=status.HTTP_201_CREATED)
async def create_connection(body: ConnectionCreate, caller: Caller, integrations: Integrations) -> Connection:
    values = body.model_dump()
    values["owner_type"] = "tenant" if values.get("owner_type") == "workspace" else values.get("owner_type")
    return Connection.model_validate(_connection_payload(await integrations.create_connection(caller, values)))


@router.post("/connections/authorizations", response_model=ConnectionAuthorization, status_code=status.HTTP_201_CREATED)
async def create_connection_authorization(body: ConnectionAuthorizationCreate, caller: Caller, integrations: Integrations) -> ConnectionAuthorization:
    started = integrations.start_authorization(caller, connector_key=body.connector_key, owner_type="tenant" if body.owner_type == "workspace" else body.owner_type, integration_connection_id=body.connection_id)
    return ConnectionAuthorization(authorization_url=started.authorization_url, nonce=started.nonce)


@router.get("/connections/{connection_id}", response_model=Connection)
async def get_connection(connection_id: UUID, caller: Caller, integrations: Integrations) -> Connection:
    return Connection.model_validate(_connection_payload(await integrations.get_connection(caller, connection_id)))


@router.patch("/connections/{connection_id}", response_model=Connection)
async def update_connection(connection_id: UUID, body: ConnectionUpdate, caller: Caller, integrations: Integrations) -> Connection:
    changes = body.model_dump(exclude_unset=True)
    result = await (integrations.disconnect_connection(caller, connection_id) if changes.pop("status", None) else integrations.update_connection(caller, connection_id, changes))
    return Connection.model_validate(_connection_payload(result))


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: UUID, caller: Caller, integrations: Integrations) -> Response:
    await integrations.delete_connection(caller, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connections/{connection_id}/validate", response_model=ConnectionValidation)
async def validate_connection(connection_id: UUID, caller: Caller, integrations: Integrations) -> ConnectionValidation:
    return ConnectionValidation.model_validate(await integrations.validate_connection(caller, connection_id))


@router.get("/connections/{connection_id}/resources", response_model=ProviderResourcePage)
async def list_connection_resources(connection_id: UUID, caller: Caller, integrations: Integrations, parent_id: str | None = None, search: str | None = None) -> ProviderResourcePage:
    value = await integrations.list_connection_resources(caller, connection_id, parent_id=parent_id, search=search)
    return ProviderResourcePage(items=value.get("items", []))


@router.post("/connections/{connection_id}/sources", response_model=Source, status_code=status.HTTP_201_CREATED)
async def create_connection_source(connection_id: UUID, body: SourceCreate, caller: Caller, integrations: Integrations) -> Source:
    values = body.model_dump()
    values["target_item_id"] = values.pop("collection_id")
    return Source.model_validate(_source_payload(await integrations.create_source(caller, connection_id, values)))


@router.get("/sources", response_model=SourcePage)
async def list_sources(caller: Caller, integrations: Integrations, page: int = 1, page_size: int = 20, connection_id: UUID | None = None) -> SourcePage:
    value = await integrations.list_sources(caller, page=page, page_size=page_size, integration_connection_id=connection_id)
    return SourcePage(items=[_source_payload(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.get("/sources/{source_id}", response_model=Source)
async def get_source(source_id: UUID, caller: Caller, integrations: Integrations) -> Source:
    return Source.model_validate(_source_payload(await integrations.get_source(caller, source_id)))


@router.patch("/sources/{source_id}", response_model=Source)
async def update_source(source_id: UUID, body: SourceUpdate, caller: Caller, integrations: Integrations) -> Source:
    return Source.model_validate(_source_payload(await integrations.update_source(caller, source_id, body.model_dump(exclude_unset=True))))


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: UUID, caller: Caller, integrations: Integrations) -> Response:
    await integrations.delete_source(caller, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sources/{source_id}/status", response_model=SourceStatus)
async def get_source_status(source_id: UUID, caller: Caller, integrations: Integrations) -> SourceStatus:
    value = await integrations.get_source_status(caller, source_id)
    return SourceStatus(source_id=source_id, source_status=value.get("source_status", "failed"), connection_status=value.get("connection_status", "error"), latest_ingestion=_ingestion_payload(value["workflow"]) if value.get("workflow") else None)


@router.post("/sources/{source_id}/ingestions", response_model=Ingestion, status_code=status.HTTP_202_ACCEPTED)
async def create_source_ingestion(source_id: UUID, caller: Caller, integrations: Integrations) -> Ingestion:
    return Ingestion.model_validate(_ingestion_payload(await integrations.ingest_source(caller, source_id)))


@router.get("/sources/{source_id}/ingestions", response_model=IngestionPage)
async def list_source_ingestions(source_id: UUID, caller: Caller, integrations: Integrations, page: int = 1, page_size: int = 20) -> IngestionPage:
    value = await integrations.list_source_workflows(caller, source_id, page=page, page_size=page_size)
    return IngestionPage(items=[_ingestion_payload(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.get("/sources/{source_id}/ingestions/{ingestion_id}", response_model=Ingestion)
async def get_source_ingestion(source_id: UUID, ingestion_id: UUID, caller: Caller, integrations: Integrations) -> Ingestion:
    value = await integrations.get_ingestion_by_public_id(caller, ingestion_id)
    if str(value.get("source_id")) != str(source_id):
        raise ControlPlaneNotFoundError(f"ingestion not found: {ingestion_id}")
    return Ingestion.model_validate(_ingestion_payload(value))


@router.get("/sources/{source_id}/schedule", response_model=Schedule)
async def get_source_schedule(source_id: UUID, caller: Caller, integrations: Integrations) -> Schedule:
    return Schedule.model_validate(await integrations.get_source_schedule(caller, source_id))


@router.put("/sources/{source_id}/schedule", response_model=Schedule)
async def put_source_schedule(source_id: UUID, body: SchedulePut, caller: Caller, integrations: Integrations) -> Schedule:
    return Schedule.model_validate(await integrations.set_source_schedule(caller, source_id, body.model_dump()))


@router.patch("/sources/{source_id}/schedule", response_model=Schedule)
async def patch_source_schedule(source_id: UUID, body: SchedulePatch, caller: Caller, integrations: Integrations) -> Schedule:
    current = await integrations.get_source_schedule(caller, source_id)
    current.update(body.model_dump(exclude_unset=True))
    return Schedule.model_validate(await integrations.set_source_schedule(caller, source_id, current))


@router.delete("/sources/{source_id}/schedule", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_schedule(source_id: UUID, caller: Caller, integrations: Integrations) -> Response:
    await integrations.delete_source_schedule(caller, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/ingestions", response_model=IngestionPage)
async def list_ingestions(caller: Caller, integrations: Integrations, page: int = 1, page_size: int = 20, source_id: UUID | None = None, connection_id: UUID | None = None, status: str | None = None) -> IngestionPage:
    value = await integrations.list_ingestion_jobs(caller, page=page, page_size=page_size, source_id=source_id, integration_connection_id=connection_id, status=status)
    return IngestionPage(items=[_ingestion_payload(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.get("/ingestions/{ingestion_id}", response_model=Ingestion)
async def get_ingestion(ingestion_id: UUID, caller: Caller, integrations: Integrations) -> Ingestion:
    return Ingestion.model_validate(_ingestion_payload(await integrations.get_ingestion_by_public_id(caller, ingestion_id)))


@router.post("/ingestions/{ingestion_id}/retry", response_model=Ingestion, status_code=status.HTTP_202_ACCEPTED)
async def retry_ingestion(ingestion_id: UUID, caller: Caller, integrations: Integrations) -> Ingestion:
    return Ingestion.model_validate(_ingestion_payload(await integrations.retry_ingestion_by_public_id(caller, ingestion_id)))


@router.post("/ingestions/{ingestion_id}/cancel", response_model=Ingestion)
async def cancel_ingestion(ingestion_id: UUID, caller: Caller, integrations: Integrations) -> Ingestion:
    return Ingestion.model_validate(_ingestion_payload(await integrations.cancel_ingestion_by_public_id(caller, ingestion_id)))


# Workspace and IAM -------------------------------------------------------
@router.get("/workspaces", response_model=WorkspacePage)
async def list_workspaces_contract(caller: Caller, control_plane: WorkspaceControlPlane) -> WorkspacePage:
    value = await control_plane.list_workspaces(caller)
    return WorkspacePage(items=[_workspace_payload(item) for item in value.get("items", [])], page=value.get("page", 1), page_size=value.get("page_size", max(1, len(value.get("items", [])))), total=value.get("total", 0))


@router.get("/workspaces/{workspace_id}", response_model=Workspace)
async def get_workspace_contract(workspace_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> Workspace:
    return Workspace.model_validate(_workspace_payload(await control_plane.get_workspace(caller, workspace_id)))


@router.patch("/workspaces/{workspace_id}", response_model=Workspace)
async def update_workspace_contract(workspace_id: UUID, body: WorkspaceUpdate, caller: Caller, control_plane: WorkspaceControlPlane) -> Workspace:
    return Workspace.model_validate(_workspace_payload(await control_plane.update_workspace(caller, workspace_id, body.model_dump(exclude_unset=True))))


@router.get("/workspaces/{workspace_id}/overview", response_model=WorkspaceOverview)
async def get_workspace_overview(workspace_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> WorkspaceOverview:
    value = await control_plane.workspace_overview(caller)
    workspace = value.get("workspace") or await control_plane.get_workspace(caller, workspace_id)
    return WorkspaceOverview(workspace=Workspace.model_validate(_workspace_payload(workspace)), metrics=value.get("metrics", {}), attention=value.get("attention", {}), recent_activity=value.get("recent_activity", []), generated_at=value.get("generated_at") or datetime.now())


@router.get("/users", response_model=UserPage)
async def list_users_contract(caller: Caller, control_plane: WorkspaceControlPlane, page: int = 1, page_size: int = 20, search: str | None = None) -> UserPage:
    value = await control_plane.list_users(caller, page=page, page_size=page_size, search=search)
    return UserPage(items=[_user_payload(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.post("/users", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user_contract(body: UserCreate, caller: Caller, control_plane: WorkspaceControlPlane) -> User:
    return User.model_validate(_user_payload(await control_plane.create_user(caller, body.model_dump())))


@router.get("/users/{user_id}", response_model=User)
async def get_user_contract(user_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> User:
    return User.model_validate(_user_payload(await control_plane.get_user(caller, user_id)))


@router.patch("/users/{user_id}", response_model=User)
async def update_user_contract(user_id: UUID, body: UserUpdate, caller: Caller, control_plane: WorkspaceControlPlane) -> User:
    return User.model_validate(_user_payload(await control_plane.update_user(caller, user_id, body.model_dump(exclude_unset=True))))


@router.get("/roles", response_model=RolePage)
async def list_roles_contract(caller: Caller, control_plane: WorkspaceControlPlane, page: int = 1, page_size: int = 20, search: str | None = None) -> RolePage:
    value = await control_plane.list_roles(caller, page=page, page_size=page_size, search=search)
    return RolePage(items=[_role_payload(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.post("/roles", response_model=Role, status_code=status.HTTP_201_CREATED)
async def create_role_contract(body: RoleCreate, caller: Caller, control_plane: WorkspaceControlPlane) -> Role:
    return Role.model_validate(_role_payload(await control_plane.create_role(caller, body.model_dump())))


@router.get("/roles/{role_id}", response_model=Role)
async def get_role_contract(role_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> Role:
    return Role.model_validate(_role_payload(await control_plane.get_role(caller, role_id)))


@router.patch("/roles/{role_id}", response_model=Role)
async def update_role_contract(role_id: UUID, body: RoleUpdate, caller: Caller, control_plane: WorkspaceControlPlane) -> Role:
    return Role.model_validate(_role_payload(await control_plane.update_role(caller, role_id, body.model_dump(exclude_unset=True))))


@router.get("/groups", response_model=GroupPage)
async def list_groups_contract(caller: Caller, control_plane: WorkspaceControlPlane, page: int = 1, page_size: int = 20, search: str | None = None) -> GroupPage:
    value = await control_plane.list_groups(caller, page=page, page_size=page_size, search=search)
    return GroupPage(items=value.get("items", []), page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.post("/groups", response_model=Group, status_code=status.HTTP_201_CREATED)
async def create_group_contract(body: GroupCreate, caller: Caller, control_plane: WorkspaceControlPlane) -> Group:
    return Group.model_validate(await control_plane.create_group(caller, body.model_dump()))


@router.get("/groups/{group_id}", response_model=Group)
async def get_group_contract(group_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> Group:
    return Group.model_validate(await control_plane.get_group(caller, group_id))


@router.patch("/groups/{group_id}", response_model=Group)
async def update_group_contract(group_id: UUID, body: GroupUpdate, caller: Caller, control_plane: WorkspaceControlPlane) -> Group:
    return Group.model_validate(await control_plane.update_group(caller, group_id, body.model_dump(exclude_unset=True)))


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_contract(group_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> Response:
    await control_plane.delete_group(caller, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/groups/{group_id}/members", response_model=Group)
async def replace_group_members(group_id: UUID, body: GroupMembersUpdate, caller: Caller, control_plane: WorkspaceControlPlane) -> Group:
    return Group.model_validate(await control_plane.replace_group_members(caller, group_id, body.user_ids))


@router.get("/permissions", response_model=PermissionPage)
async def list_permissions(caller: Caller, control_plane: WorkspaceControlPlane) -> PermissionPage:
    value = await control_plane.list_permissions(caller)
    return PermissionPage(items=[Permission.model_validate(item) for item in value.get("items", [])], total=value.get("total", 0))


@router.get("/approval-requests", response_model=ApprovalRequestPage)
async def list_approval_requests(caller: Caller, control_plane: WorkspaceControlPlane, page: int = 1, page_size: int = 20) -> ApprovalRequestPage:
    value = await control_plane.list_approval_requests(caller, page=page, page_size=page_size)
    return ApprovalRequestPage(items=[ApprovalRequest.model_validate(_approval_payload(item)) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.post("/approval-requests", response_model=ApprovalRequest, status_code=status.HTTP_201_CREATED)
async def create_approval_request(body: ApprovalRequestCreate, caller: Caller, control_plane: WorkspaceControlPlane) -> ApprovalRequest:
    return ApprovalRequest.model_validate(_approval_payload(await control_plane.create_approval_request(caller, body.model_dump())))


@router.get("/approval-requests/{approval_request_id}", response_model=ApprovalRequest)
async def get_approval_request(approval_request_id: UUID, caller: Caller, control_plane: WorkspaceControlPlane) -> ApprovalRequest:
    return ApprovalRequest.model_validate(_approval_payload(await control_plane.get_approval_request(caller, approval_request_id)))


@router.patch("/approval-requests/{approval_request_id}", response_model=ApprovalRequest)
async def update_approval_request(approval_request_id: UUID, body: ApprovalRequestUpdate, caller: Caller, control_plane: WorkspaceControlPlane) -> ApprovalRequest:
    return ApprovalRequest.model_validate(_approval_payload(await control_plane.update_approval_request(caller, approval_request_id, body.model_dump())))


@router.get("/audit-logs", response_model=AuditLogPage)
async def list_audit_logs(caller: Caller, control_plane: WorkspaceControlPlane, page: int = 1, page_size: int = 20, search: str | None = None) -> AuditLogPage:
    value = await control_plane.list_audit_logs(caller, page=page, page_size=page_size, search=search)
    return AuditLogPage(items=[AuditLog.model_validate(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.get("/platform/overview", response_model=PlatformOverview)
async def get_platform_overview(caller: Caller, control_plane: WorkspaceControlPlane) -> PlatformOverview:
    return PlatformOverview.model_validate(await control_plane.platform_overview(caller))


@router.get("/platform/health")
async def get_platform_health(health: Health) -> dict[str, Any]:
    return (await health.check()).model_dump(mode="json")


@router.get("/platform/workspaces", response_model=WorkspacePage)
async def list_platform_workspaces(caller: Caller, control_plane: WorkspaceControlPlane, page: int = 1, page_size: int = 20, search: str | None = None, status: str | None = None) -> WorkspacePage:
    value = await control_plane.list_platform_workspaces(caller, page=page, page_size=page_size, search=search, status=status)
    return WorkspacePage(items=[_workspace_payload(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.get("/platform/users", response_model=UserPage)
async def list_platform_users(caller: Caller, control_plane: WorkspaceControlPlane, page: int = 1, page_size: int = 20, search: str | None = None, status: bool | None = None) -> UserPage:
    value = await control_plane.list_platform_users(caller, page=page, page_size=page_size, search=search, status=status)
    return UserPage(items=[_user_payload(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


@router.get("/platform/audit-logs", response_model=AuditLogPage)
async def list_platform_audit_logs(caller: Caller, control_plane: WorkspaceControlPlane, page: int = 1, page_size: int = 20, search: str | None = None) -> AuditLogPage:
    value = await control_plane.list_platform_audit_logs(caller, page=page, page_size=page_size, search=search)
    return AuditLogPage(items=[AuditLog.model_validate(item) for item in value.get("items", [])], page=value.get("page", page), page_size=value.get("page_size", page_size), total=value.get("total", 0))


__all__ = ["router"]
