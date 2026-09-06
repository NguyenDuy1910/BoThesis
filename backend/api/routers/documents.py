"""Document routes: upload, complete, retry, search, inspect, and delete."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Header, UploadFile, status

from api.deps import Caller, Documents, KnowledgeQuery
from api.routers import (
    CollectionDocumentUploadResponse,
    DocumentMetadata,
    DocumentUploadStartRequest,
    DocumentUploadStartResponse,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])
collections_router = APIRouter(prefix="/collections", tags=["collections"])

IdempotencyKey = Annotated[
    str, Header(min_length=1, max_length=128, alias="Idempotency-Key")
]


@collections_router.post(
    "/{collection_id}/documents/upload",
    response_model=CollectionDocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_collection_document(
    collection_id: UUID,
    caller: Caller,
    documents: Documents,
    file: Annotated[UploadFile, File(...)],
    idempotency_key: IdempotencyKey,
) -> CollectionDocumentUploadResponse:
    return CollectionDocumentUploadResponse.model_validate(
        await documents.upload_to_collection(
            caller,
            collection_id,
            idempotency_key=idempotency_key,
            file_name=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            content=file,
        )
    )


@router.post(
    "/uploads",
    response_model=DocumentUploadStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_document_upload(
    body: DocumentUploadStartRequest,
    caller: Caller,
    documents: Documents,
    idempotency_key: IdempotencyKey,
) -> DocumentUploadStartResponse:
    return DocumentUploadStartResponse.model_validate(
        await documents.start_upload(
            caller,
            idempotency_key=idempotency_key,
            file_name=body.file_name,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    )


@router.post("/{document_id}/complete", response_model=DocumentMetadata)
async def complete_document_upload(
    document_id: UUID, caller: Caller, documents: Documents
) -> DocumentMetadata:
    return DocumentMetadata.model_validate(
        await documents.complete_upload(caller, document_id)
    )


@router.post("/{document_id}/retry", response_model=CollectionDocumentUploadResponse)
async def retry_document_indexing(
    document_id: UUID, caller: Caller, documents: Documents
) -> CollectionDocumentUploadResponse:
    return CollectionDocumentUploadResponse.model_validate(
        await documents.retry_indexing(caller, document_id)
    )


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    body: SearchRequest, caller: Caller, knowledge: KnowledgeQuery
) -> SearchResponse:
    """Permission-filtered semantic search across all indexed sources."""

    return SearchResponse.model_validate(
        await knowledge.search(
            caller,
            query=body.query,
            top_k=body.top_k,
            collection_item_ids=body.collection_item_ids,
        )
    )


@router.get("/{doc_id}", response_model=DocumentMetadata)
async def get_document(
    doc_id: UUID, caller: Caller, documents: Documents
) -> DocumentMetadata:
    return DocumentMetadata.model_validate(await documents.get_document(caller, doc_id))


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID, caller: Caller, documents: Documents
) -> None:
    await documents.delete_document(caller, doc_id)
