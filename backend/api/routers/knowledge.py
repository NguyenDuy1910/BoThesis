"""Knowledge routes: resolve a citation or open a document viewer."""

from __future__ import annotations

from fastapi import APIRouter, Query

from api.deps import Caller, KnowledgeView
from api.routers import KnowledgeCitationResponse, KnowledgeItemViewer

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


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
