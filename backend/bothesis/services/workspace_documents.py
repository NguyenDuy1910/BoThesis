"""Workspace document lifecycle: upload, index, inspect, and delete."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from bothesis.db.engine import SessionFactory, session_scope
from bothesis.db.models import Item
from bothesis.services import AsyncUploadStream, AuthContext
from bothesis.services.audit import AuditService
from bothesis.services.collection_access import CollectionAccessService
from bothesis.services.document_presentation import DocumentPresenter
from bothesis.services.document_upload import DocumentUploadService

IngestionStatus = Literal["ready", "failed"]


class WorkspaceDocumentService:
    """Own the document workflows a signed-in workspace user drives."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        uploads: DocumentUploadService,
        presenter: DocumentPresenter,
    ) -> None:
        self._sessions = session_factory
        self._uploads = uploads
        self._presenter = presenter

    async def list_collections(self, access: AuthContext) -> dict[str, Any]:
        """List the Collections the caller may select for a chat turn."""

        async with session_scope(self._sessions) as session:
            ids = await CollectionAccessService(session).allowed_collection_ids(access)
            if not ids:
                return {"items": [], "total": 0}
            collections = list(
                await session.scalars(
                    select(Item).where(Item.id.in_(ids)).order_by(Item.title, Item.id)
                )
            )
        return {
            "items": [
                {
                    "id": str(item.id),
                    "title": item.title,
                    "parent_item_id": (
                        str(item.parent_item_id) if item.parent_item_id else None
                    ),
                }
                for item in collections
            ],
            "total": len(collections),
        }

    async def start_upload(
        self,
        access: AuthContext,
        *,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        size_bytes: int,
    ) -> dict[str, Any]:
        """Reserve a document and, when needed, a presigned upload target."""

        result = await self._uploads.start_upload(
            access,
            idempotency_key=idempotency_key,
            file_name=file_name,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        return {
            "upload_required": result.upload_required,
            "target": self._presenter.upload_target(result.target),
            "document": self._presenter.metadata(result.item),
        }

    async def complete_upload(
        self, access: AuthContext, document_id: UUID
    ) -> dict[str, Any]:
        """Mark a presigned upload available and index its content."""

        document = await self._uploads.complete_upload(access, document_id)
        return self._presenter.metadata(document)

    async def upload_to_collection(
        self,
        access: AuthContext,
        collection_id: UUID,
        *,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        content: AsyncUploadStream,
    ) -> dict[str, Any]:
        """Store and index a native upload under one authorized Collection."""

        upload = await self._uploads.upload_to_collection(
            access,
            collection_id,
            idempotency_key=idempotency_key,
            file_name=file_name,
            content_type=content_type,
            content=content,
        )
        document = upload.item
        ingestion_status = _ingestion_status(document)
        await self._record(
            access,
            action="document.uploaded",
            document_id=document.id,
            details={
                "collection_id": str(collection_id),
                "created": upload.created,
                "ingestion_status": ingestion_status,
            },
        )
        return {
            "document": self._presenter.metadata(document),
            "ingestion_status": ingestion_status,
            "created": upload.created,
        }

    async def retry_indexing(
        self, access: AuthContext, document_id: UUID
    ) -> dict[str, Any]:
        """Retry indexing from an already available native upload."""

        document = await self._uploads.retry_indexing(access, document_id)
        ingestion_status = _ingestion_status(document)
        await self._record(
            access,
            action="document.indexing.retried",
            document_id=document.id,
            details={"ingestion_status": ingestion_status},
        )
        return {
            "document": self._presenter.metadata(document),
            "ingestion_status": ingestion_status,
            "created": False,
        }

    async def get_document(
        self, access: AuthContext, document_id: UUID
    ) -> dict[str, Any]:
        document = await self._uploads.get_document(access, document_id)
        return self._presenter.metadata(document)

    async def delete_document(self, access: AuthContext, document_id: UUID) -> None:
        await self._uploads.delete_document(access, document_id)

    async def _record(
        self,
        access: AuthContext,
        *,
        action: str,
        document_id: UUID,
        details: dict[str, Any],
    ) -> None:
        async with session_scope(self._sessions) as session:
            await AuditService(session).record(
                access,
                action=action,
                resource_type="document",
                resource_id=str(document_id),
                details=details,
            )


def _ingestion_status(document: Any) -> IngestionStatus:
    return "ready" if document.status == "ready" else "failed"


__all__ = ["IngestionStatus", "WorkspaceDocumentService"]
