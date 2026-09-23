"""Workspace document lifecycle: upload, index, inspect, and delete."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from bothesis.db.engine import SessionFactory, transaction_scope
from bothesis.db.models import Item
from bothesis.services import (
    KNOWLEDGE_READ_PERMISSION,
    AsyncUploadStream,
    AuthContext,
    AuthorizationError,
    require_user_identity,
    require_tenant_permission,
)
from bothesis.services.audit import AuditService
from bothesis.services.document_presentation import DocumentPresenter
from bothesis.services.document_upload import DocumentUploadService
from bothesis.services.identity_access.authorization import AuthorizationService
from bothesis.services.item import ItemService

IngestionStatus = Literal["pending", "processing", "ready", "failed", "unsupported"]


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

        async with transaction_scope(self._sessions) as session:
            ids = await AuthorizationService(session).allowed_collection_ids(access)
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

    async def ensure_personal_collection(self, access: AuthContext) -> dict[str, Any]:
        """Return the caller's private upload Collection, creating it once."""

        if access.is_guest:
            raise AuthorizationError("sign in is required for private uploads")
        user_id = require_user_identity(access)
        tenant_id = require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        collection_id = ItemService.upload_collection_id(tenant_id, user_id)
        async with transaction_scope(self._sessions) as session:
            items = ItemService(session)
            await items.ensure_personal_collection(
                user_id,
                tenant_id,
                collection_id=collection_id,
                title="My uploads",
                system_kind="personal_uploads",
            )
            collection = await session.get(Item, collection_id)
            if collection is None:
                raise RuntimeError("personal Collection could not be created")
            return {"id": collection.id, "title": collection.title}

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

    async def create_document(
        self,
        access: AuthContext,
        collection_id: UUID,
        *,
        idempotency_key: str,
        name: str,
        content_type: str,
        size_bytes: int | None = None,
        purpose: str = "knowledge",
        content: AsyncUploadStream | None = None,
    ) -> dict[str, Any]:
        """Create one Document through either direct or presigned transport."""

        if content is None:
            if size_bytes is None:
                raise ValueError("size_bytes is required for presigned creation")
            result = await self._uploads.start_upload(
                access, collection_id=collection_id, idempotency_key=idempotency_key,
                file_name=name, content_type=content_type, size_bytes=size_bytes,
                purpose=purpose,
            )
            return {
                "document": self._presenter.contract_document(result.item),
                "upload": self._presenter.upload_target(result.target),
                "ingestion": None,
                "created": result.created,
            }
        upload = await self._uploads.upload_to_collection(
            access, collection_id, idempotency_key=idempotency_key,
            file_name=name, content_type=content_type, content=content, purpose=purpose,
        )
        return {
            "document": self._presenter.contract_document(upload.item),
            "upload": None,
            "ingestion": None,
            "created": upload.created,
        }

    async def complete_upload(
        self, access: AuthContext, document_id: UUID
    ) -> dict[str, Any]:
        """Mark a personal upload available without ingesting its content."""

        document = await self._uploads.complete_upload(access, document_id)
        return self._presenter.metadata(document)

    async def finalize_document_content(
        self, access: AuthContext, document_id: UUID
    ) -> dict[str, Any]:
        document = await self._uploads.complete_upload(access, document_id)
        return {
            "document": self._presenter.contract_document(document),
            "ingestion": None,
        }

    async def get_contract_document(
        self, access: AuthContext, document_id: UUID
    ) -> dict[str, Any]:
        document = await self._uploads.get_document(access, document_id)
        return self._presenter.contract_document(document)

    async def list_documents(
        self,
        access: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        collection_id: UUID | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        async with transaction_scope(self._sessions) as session:
            allowed = await AuthorizationService(session).allowed_collection_ids(access)
            if collection_id is not None:
                allowed = tuple(item for item in allowed if item == collection_id)
            statement = select(Item).where(
                Item.item_type == "document",
                Item.parent_item_id.in_(allowed),
                Item.deleted_at.is_(None),
            ).options(joinedload(Item.upload))
            if search:
                statement = statement.where(Item.title.ilike(f"%{search}%"))
            if status:
                internal_statuses = {
                    "pending_content": ("pending",),
                    "available": ("processing", "ready"),
                    "failed": ("failed", "unsupported"),
                }.get(status)
                if internal_statuses is not None:
                    statement = statement.where(Item.status.in_(internal_statuses))
            total = await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            items = list(await session.scalars(
                statement.order_by(Item.updated_at.desc(), Item.id)
                .offset((page - 1) * page_size).limit(page_size)
            ))
            return {
                "items": [self._presenter.contract_document(item) for item in items],
                "page": page,
                "page_size": page_size,
                "total": int(total),
            }

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
        """Store a native upload and queue its independent indexing lifecycle."""

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
        async with transaction_scope(self._sessions) as session:
            await AuditService(session).record(
                access,
                action=action,
                resource_type="document",
                resource_id=str(document_id),
                details=details,
            )


def _ingestion_status(document: Any) -> IngestionStatus:
    status = getattr(document, "index_status", None)
    if status in {"pending", "processing", "ready", "failed", "unsupported"}:
        return status
    return "failed"


__all__ = ["IngestionStatus", "WorkspaceDocumentService"]
