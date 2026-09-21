"""Collection resources and collection access control."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from api.deps import Caller, Documents, WorkspaceControlPlane
from api.routers import (
    Collection,
    CollectionAccess,
    CollectionAccessPage,
    CollectionAccessUpdate,
    CollectionCreate,
    CollectionPage,
    CollectionUpdate,
)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("", response_model=CollectionPage)
async def list_collections(
    caller: Caller,
    control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> CollectionPage:
    return CollectionPage.model_validate(
        await control_plane.list_collections(
            caller, page=page, page_size=page_size, search=search
        )
    )


@router.post("", response_model=Collection, status_code=status.HTTP_201_CREATED)
async def create_collection(
    body: CollectionCreate,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Collection:
    values = {
        "title": body.title,
        "parent_item_id": body.parent_collection_id,
        "inherit_access": body.inherit_access,
        "metadata": (
            {"description": body.description}
            if body.description is not None
            else {}
        ),
    }
    return Collection.model_validate(
        await control_plane.create_collection_contract(caller, values)
    )


@router.put("/personal", response_model=Collection)
async def ensure_personal_collection(
    caller: Caller,
    documents: Documents,
    control_plane: WorkspaceControlPlane,
) -> Collection:
    value = await documents.ensure_personal_collection(caller)
    return Collection.model_validate(
        await control_plane.get_collection(caller, UUID(str(value["id"])))
    )


@router.get("/{collection_id}", response_model=Collection)
async def get_collection(
    collection_id: UUID,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Collection:
    return Collection.model_validate(
        await control_plane.get_collection(caller, collection_id)
    )


@router.patch("/{collection_id}", response_model=Collection)
async def update_collection(
    collection_id: UUID,
    body: CollectionUpdate,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Collection:
    return Collection.model_validate(
        await control_plane.update_collection_contract(
            caller, collection_id, body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: UUID,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Response:
    await control_plane.delete_collection(caller, collection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{collection_id}/access", response_model=CollectionAccessPage)
async def list_collection_access(
    collection_id: UUID,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CollectionAccessPage:
    return CollectionAccessPage.model_validate(
        await control_plane.list_collection_access(
            caller, collection_id, page=page, page_size=page_size
        )
    )


@router.put(
    "/{collection_id}/access/{principal_type}/{principal_id}",
    response_model=CollectionAccess,
)
async def put_collection_access(
    collection_id: UUID,
    principal_type: Literal["user", "group"],
    principal_id: UUID,
    body: CollectionAccessUpdate,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> CollectionAccess:
    value = await control_plane.grant_collection_access(
        caller,
        collection_id,
        {
            "principal_type": principal_type,
            "principal_id": principal_id,
            "role_code": f"collection_{body.role}",
        },
    )
    return CollectionAccess.model_validate(
        {
            "collection_id": collection_id,
            "principal_type": principal_type,
            "principal_id": principal_id,
            "role": body.role,
            "created_at": value.get("created_at"),
            "updated_at": value.get("updated_at"),
        }
    )


@router.delete(
    "/{collection_id}/access/{principal_type}/{principal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_collection_access(
    collection_id: UUID,
    principal_type: Literal["user", "group"],
    principal_id: UUID,
    caller: Caller,
    control_plane: WorkspaceControlPlane,
) -> Response:
    await control_plane.revoke_collection_access(
        caller,
        collection_id,
        principal_type=principal_type,
        principal_id=principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
