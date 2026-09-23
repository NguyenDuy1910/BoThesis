"""Permission-filtered knowledge projections."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import Caller, KnowledgeView
from api.routers import Collection, Document, DocumentStatus, KnowledgeHomeResponse
from bothesis.services.document_presentation import public_document_status


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


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/home", response_model=KnowledgeHomeResponse)
async def get_knowledge_home(
    caller: Caller, knowledge: KnowledgeView
) -> KnowledgeHomeResponse:
    value = await knowledge.get_workspace_home(caller)
    return KnowledgeHomeResponse(
        collections=[
            Collection.model_validate(item) for item in value.get("items", [])
        ],
        recent_documents=[
            Document.model_validate(item)
            for item in value.get("recent_documents", [])
        ],
        personal_collection_id=value.get("personal_collection_id"),
    )


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentViewer)
async def get_knowledge_document(
    document_id: UUID,
    caller: Caller,
    knowledge: KnowledgeView,
    chunk: str | None = None,
) -> KnowledgeDocumentViewer:
    value = await knowledge.get_item(
        caller, item_id=str(document_id), chunk_id=chunk
    )
    value["document_id"] = value.pop("item_id")
    value["status"] = public_document_status(value.get("status"))
    return KnowledgeDocumentViewer.model_validate(value)


@router.get(
    "/documents/{document_id}/citations/{chunk_id}",
    response_model=KnowledgeDocumentCitation,
)
async def get_knowledge_document_citation(
    document_id: UUID,
    chunk_id: str,
    caller: Caller,
    knowledge: KnowledgeView,
) -> KnowledgeDocumentCitation:
    value = await knowledge.get_citation(
        caller, item_id=str(document_id), chunk_id=chunk_id
    )
    value["document_id"] = value.pop("item_id")
    return KnowledgeDocumentCitation.model_validate(value)


__all__ = ["router"]
