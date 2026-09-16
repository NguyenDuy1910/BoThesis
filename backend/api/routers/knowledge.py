"""Knowledge routes: resolve a citation or open a document viewer."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from api.deps import AdminConsole, Caller, Documents, KnowledgeView
from api.routers import (
    KnowledgeCitationResponse,
    KnowledgeCollectionCreate,
    KnowledgeCollectionCreated,
    KnowledgeCollectionWorkspaceResponse,
    KnowledgeHomeResponse,
    KnowledgeItemViewer,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.put(
    "/collections/personal",
    response_model=KnowledgeCollectionCreated,
    status_code=status.HTTP_200_OK,
)
async def ensure_personal_collection(
    caller: Caller,
    documents: Documents,
) -> KnowledgeCollectionCreated:
    """Provision the caller's private upload Collection idempotently."""

    return KnowledgeCollectionCreated.model_validate(
        await documents.ensure_personal_collection(caller)
    )


@router.post(
    "/collections",
    response_model=KnowledgeCollectionCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_collection(
    body: KnowledgeCollectionCreate,
    caller: Caller,
    admin: AdminConsole,
) -> KnowledgeCollectionCreated:
    """Create a governed Collection without leaving the knowledge workspace."""

    collection = await admin.create_collection(
        caller,
        {
            "title": body.title,
            "inherit_access": True,
            "metadata": (
                {"description": body.description.strip()}
                if body.description and body.description.strip()
                else {}
            ),
        },
    )
    return KnowledgeCollectionCreated.model_validate(collection)


@router.get("/collections", response_model=KnowledgeHomeResponse)
async def get_knowledge_home(
    caller: Caller,
    knowledge: KnowledgeView,
) -> KnowledgeHomeResponse:
    """List only the Collections and recent Items available to the caller."""

    return KnowledgeHomeResponse.model_validate(
        await knowledge.get_workspace_home(caller)
    )


@router.get(
    "/collections/{collection_id}",
    response_model=KnowledgeCollectionWorkspaceResponse,
)
async def get_knowledge_collection_workspace(
    collection_id: UUID,
    caller: Caller,
    knowledge: KnowledgeView,
    search: str | None = Query(default=None, min_length=1, max_length=160),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> KnowledgeCollectionWorkspaceResponse:
    """Return one authorized Collection with its direct child knowledge Items."""

    return KnowledgeCollectionWorkspaceResponse.model_validate(
        await knowledge.get_collection_workspace(
            caller,
            collection_id=collection_id,
            search=search,
            page=page,
            page_size=page_size,
        )
    )


@router.get(
    "/items/{item_id:path}/citations/{chunk_id:path}",
    response_model=KnowledgeCitationResponse,
)
async def get_knowledge_citation(
    item_id: str,
    chunk_id: str,
    caller: Caller,
    knowledge: KnowledgeView,
) -> KnowledgeCitationResponse:
    return KnowledgeCitationResponse.model_validate(
        await knowledge.get_citation(caller, item_id=item_id, chunk_id=chunk_id)
    )


@router.get("/items/{item_id:path}", response_model=KnowledgeItemViewer)
async def get_knowledge_item_viewer(
    item_id: str,
    caller: Caller,
    knowledge: KnowledgeView,
    chunk: str | None = Query(default=None, min_length=1, max_length=512),
) -> KnowledgeItemViewer:
    return KnowledgeItemViewer.model_validate(
        await knowledge.get_item(caller, item_id=item_id, chunk_id=chunk)
    )
