"""Tenant document inventory and lifecycle administration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import Connector, ConnectorScope, Document, DocumentChunk
from bothesis.services import (
    DOCUMENT_MANAGE_PERMISSION,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    DatasourceService,
    DocumentService,
    normalize_page,
    require_tenant_permission,
    timestamp,
)

_LIFECYCLE_STATUSES = frozenset(
    {"active", "retired", "hidden", "unsupported", "failed"}
)
_INDEXING_STATUSES = frozenset({"none", "pending", "indexed", "failed"})


class AdminDocumentService:
    """Query enterprise documents and apply governed lifecycle transitions."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def list_documents(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        lifecycle_status: str | None = None,
        indexing_status: str | None = None,
        connector_id: int | None = None,
        sort: str = "updated_at",
        direction: str = "desc",
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, DOCUMENT_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            Document.tenant_id == tenant_id,
            Document.lifecycle_status != "deleted",
            Document.deleted_at.is_(None),
        ]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(Document.title.ilike(term), Document.external_id.ilike(term))
            )
        if lifecycle_status:
            normalized = lifecycle_status.strip().casefold()
            if normalized not in _LIFECYCLE_STATUSES:
                raise AdminValidationError("unsupported document lifecycle status")
            filters.append(Document.lifecycle_status == normalized)
        if indexing_status:
            normalized = indexing_status.strip().casefold()
            if normalized not in _INDEXING_STATUSES:
                raise AdminValidationError("unsupported document indexing status")
            filters.append(Document.indexing_status == normalized)
        if connector_id is not None:
            filters.append(Connector.id == connector_id)

        base = (
            select(Document, ConnectorScope, Connector)
            .outerjoin(
                ConnectorScope, ConnectorScope.id == Document.connector_scope_id
            )
            .outerjoin(Connector, Connector.id == ConnectorScope.connector_id)
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        sort_columns = {
            "created_at": Document.created_at,
            "indexing_status": Document.indexing_status,
            "lifecycle_status": Document.lifecycle_status,
            "title": Document.title,
            "updated_at": Document.updated_at,
        }
        sort_column = sort_columns.get(sort)
        if sort_column is None:
            raise AdminValidationError("unsupported document sort field")
        if direction not in {"asc", "desc"}:
            raise AdminValidationError("sort direction must be asc or desc")
        order = sort_column.desc() if direction == "desc" else sort_column.asc()
        rows = (
            await self._session.execute(
                base.order_by(order, Document.id).limit(page_size).offset(offset)
            )
        ).all()
        return {
            "items": [
                _document_payload(document, scope, connector)
                for document, scope, connector in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_document(
        self, actor: AuthContext, document_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, DOCUMENT_MANAGE_PERMISSION)
        row = (
            await self._session.execute(
                select(Document, ConnectorScope, Connector)
                .outerjoin(
                    ConnectorScope,
                    ConnectorScope.id == Document.connector_scope_id,
                )
                .outerjoin(Connector, Connector.id == ConnectorScope.connector_id)
                .where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                    Document.lifecycle_status != "deleted",
                    Document.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise AdminNotFoundError(f"document not found: {document_id}")
        document, scope, connector = row
        payload = _document_payload(document, scope, connector)
        chunk_count = await self._session.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.document_id == document.id,
                DocumentChunk.deleted_at.is_(None),
            )
        )
        payload.update(
            {
                "metadata": dict(document.metadata_),
                "allowed_principal_tokens": sorted(
                    document.allowed_principal_tokens
                ),
                "denied_principal_tokens": sorted(
                    document.denied_principal_tokens
                ),
                "chunk_count": int(chunk_count or 0),
                "raw_content_available": bool(
                    document.raw_storage_key or document.upload_status == "available"
                ),
            }
        )
        return payload

    async def update_lifecycle(
        self,
        actor: AuthContext,
        document_id: UUID,
        *,
        lifecycle_status: str,
    ) -> dict[str, Any]:
        require_tenant_permission(actor, DOCUMENT_MANAGE_PERMISSION)
        payload = await self.get_document(actor, document_id)
        normalized = lifecycle_status.strip().casefold()
        if normalized not in _LIFECYCLE_STATUSES:
            raise AdminValidationError("unsupported document lifecycle status")
        document = await self._session.get(Document, document_id)
        if document is None:
            raise AdminNotFoundError(f"document not found: {document_id}")
        document.lifecycle_status = normalized
        await self._session.flush()
        await self._audit.record(
            actor,
            action="document.lifecycle_updated",
            resource_type="document",
            resource_id=str(document.id),
            details={
                "previous_status": payload["lifecycle_status"],
                "lifecycle_status": normalized,
            },
        )
        return await self.get_document(actor, document_id)

    async def retry_document(
        self, actor: AuthContext, document_id: UUID
    ) -> dict[str, Any]:
        require_tenant_permission(actor, DOCUMENT_MANAGE_PERMISSION)
        payload = await self.get_document(actor, document_id)
        if payload["indexing_status"] != "failed" and payload["lifecycle_status"] != "failed":
            raise AdminConflictError(
                "only failed documents can be retried"
            )
        document = await self._session.get(Document, document_id)
        if document is None:
            raise AdminNotFoundError(f"document not found: {document_id}")
        if document.connector_scope_id is None:
            await DocumentService(self._session).mark_index_pending(document.id)
            document.lifecycle_status = "active"
            await self._audit.record(
                actor,
                action="document.retry_requested",
                resource_type="document",
                resource_id=str(document.id),
                details={"mode": "index"},
            )
            return {
                "document": await self.get_document(actor, document.id),
                "ingestion_run": None,
            }
        scope = await self._session.get(ConnectorScope, document.connector_scope_id)
        if scope is None:
            raise AdminConflictError("document datasource scope is unavailable")
        sync_result = await DatasourceService(
            self._session, audit=self._audit
        ).trigger_sync(actor, scope.connector_id, scope_id=scope.id)
        return {
            "document": payload,
            "ingestion_run": sync_result["items"][0],
        }

    async def delete_document(self, actor: AuthContext, document_id: UUID) -> None:
        require_tenant_permission(actor, DOCUMENT_MANAGE_PERMISSION)
        await self.get_document(actor, document_id)
        await DocumentService(self._session).soft_delete_document(
            document_id, actor=actor
        )
        await self._audit.record(
            actor,
            action="document.deleted",
            resource_type="document",
            resource_id=str(document_id),
        )


def _document_payload(
    document: Document,
    scope: ConnectorScope | None,
    connector: Connector | None,
) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "title": document.title,
        "origin": document.origin,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "source_url": document.source_url,
        "external_id": document.external_id,
        "external_version": document.external_version,
        "upload_status": document.upload_status,
        "indexing_status": document.indexing_status,
        "lifecycle_status": document.lifecycle_status,
        "last_synced_at": timestamp(document.last_synced_at),
        "last_indexed_at": timestamp(document.last_indexed_at),
        "created_at": timestamp(document.created_at),
        "updated_at": timestamp(document.updated_at),
        "datasource": (
            {
                "id": str(connector.id),
                "display_name": connector.display_name,
                "provider": connector.provider,
            }
            if connector is not None
            else None
        ),
        "scope": (
            {
                "id": str(scope.id),
                "display_name": scope.display_name,
                "scope_value": scope.scope_value,
                "generation": document.generation,
            }
            if scope is not None
            else None
        ),
    }


__all__ = ["AdminDocumentService"]
