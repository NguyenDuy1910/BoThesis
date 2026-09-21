"""Canonical Collection and Document HTTP resources."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from api.deps import Caller, Documents, KnowledgeQuery
from api.routers import (
    Document,
    DocumentContentResult,
    DocumentCreate,
    DocumentCreateResult,
    DocumentPage,
    DocumentSearchRequest,
    DocumentSearchResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])
collections_router = APIRouter(prefix="/collections", tags=["collections"])
IdempotencyKey = Annotated[str, Header(min_length=1, max_length=128, alias="Idempotency-Key")]


@collections_router.post(
    "/{collection_id}/documents",
    tags=["documents"],
    response_model=DocumentCreateResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="createDocument",
)
async def create_document(
    collection_id: UUID,
    caller: Caller,
    documents: Documents,
    idempotency_key: IdempotencyKey,
    request: Request,
    response: Response,
) -> DocumentCreateResult:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].casefold()
    if media_type == "multipart/form-data":
        form = await request.form()
        file = form.get("file")
        if file is None or not hasattr(file, "read"):
            raise ValueError("multipart request requires file")
        purpose = str(form.get("purpose") or "knowledge")
        result = await documents.create_document(
            caller, collection_id, idempotency_key=idempotency_key,
            name=file.filename or "document", content_type=file.content_type or "application/octet-stream",
            purpose=purpose, content=file,
        )
    else:
        body = DocumentCreate.model_validate(await request.json())
        result = await documents.create_document(
            caller, collection_id, idempotency_key=idempotency_key,
            name=body.name, content_type=body.content_type, size_bytes=body.size_bytes,
            purpose=body.purpose,
        )
    response.status_code = status.HTTP_201_CREATED if result.get("created", True) else status.HTTP_200_OK
    return DocumentCreateResult.model_validate(result)


@router.get("", response_model=DocumentPage)
async def list_documents(
    caller: Caller,
    documents: Documents,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=255)] = None,
    collection_id: UUID | None = None,
    status: str | None = None,
) -> DocumentPage:
    return DocumentPage.model_validate(await documents.list_documents(
        caller, page=page, page_size=page_size, search=search,
        collection_id=collection_id, status=status,
    ))


@router.post("/search", response_model=DocumentSearchResponse)
async def search_documents(
    body: DocumentSearchRequest, caller: Caller, knowledge: KnowledgeQuery
) -> DocumentSearchResponse:
    result = await knowledge.search(
        caller, query=body.query, top_k=body.top_k, collection_item_ids=body.collection_ids
    )
    items = [
        {
            "document_id": item.get("id") or item.get("document_id"),
            "collection_id": item.get("collection_item_id") or item.get("collection_id"),
            "name": item.get("title") or item.get("name") or "document",
            "excerpt": item.get("excerpt", ""), "score": item.get("score", 0),
            "url": item.get("url"), "metadata": item.get("metadata", {}),
        }
        for item in result.get("results", result.get("items", []))
    ]
    return DocumentSearchResponse(items=items, total=result.get("total", len(items)))


@router.get("/{document_id}", response_model=Document)
async def get_document(document_id: UUID, caller: Caller, documents: Documents) -> Document:
    return Document.model_validate(await documents.get_contract_document(caller, document_id))


@router.put("/{document_id}/content", response_model=DocumentContentResult)
async def finalize_document_content(
    document_id: UUID, caller: Caller, documents: Documents
) -> DocumentContentResult:
    return DocumentContentResult.model_validate(
        await documents.finalize_document_content(caller, document_id)
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, caller: Caller, documents: Documents) -> None:
    await documents.delete_document(caller, document_id)


__all__ = ["collections_router", "router"]
