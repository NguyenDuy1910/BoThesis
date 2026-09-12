"""Resolve citations and document viewers from indexed, authorized content."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bothesis.connector.protocol import CitationInfo
from bothesis.db.engine import SessionFactory, session_scope
from bothesis.db.models import ExternalResource, IngestionSource, Item
from bothesis.document_index import ItemIndex
from bothesis.knowledge import CitationResolver
from bothesis.services import (
    KNOWLEDGE_READ_PERMISSION,
    AuthContext,
    DocumentNotFoundError,
    require_tenant_permission,
)
from bothesis.services.citation import CitationService
from bothesis.services.identity_access.collection_access import CollectionAccessService
from bothesis.services.document_presentation import DocumentPresenter, viewer_elements
from bothesis.services.item import ItemService

VIEWER_CHUNK_LIMIT = 100


class KnowledgeViewService:
    """Serve the citation and viewer payloads the WebUI renders."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        index: ItemIndex,
        presenter: DocumentPresenter,
    ) -> None:
        self._sessions = session_factory
        self._index = index
        self._presenter = presenter

    async def get_citation(
        self,
        access: AuthContext,
        *,
        item_id: str,
        chunk_id: str,
    ) -> dict[str, Any]:
        """Return one canonical citation with its stored source links."""

        async with session_scope(self._sessions) as session:
            item, collection_id = await self._authorized_item(
                session, access, item_id, missing="citation not found"
            )
            payloads = await self._indexed_payloads(
                access,
                item_id=str(item.id),
                collection_item_id=str(collection_id),
                chunk_id=chunk_id,
                limit=1,
            )
            if not payloads:
                raise DocumentNotFoundError("citation not found")
            resolved_chunk_id = str(payloads[0].get("chunk_id") or chunk_id)
            citation = await CitationService(session).get(item.id, resolved_chunk_id)
            if citation is None:
                raise DocumentNotFoundError("citation not found")
            return {
                "item_id": str(item.id),
                "chunk_id": resolved_chunk_id,
                "title": item.title,
                "content_type": item.mime_type or "text/plain",
                "document_url": self._presenter.presigned_url(item),
                "preview": self._presenter.preview_payload(item),
                "external_url": CitationResolver.original_url(
                    self._presenter.source_identity(item), citation
                ),
                "citation": citation,
            }

    async def get_item(
        self,
        access: AuthContext,
        *,
        item_id: str,
        chunk_id: str | None,
    ) -> dict[str, Any]:
        """Return the viewer elements for one Item, optionally focused."""

        async with session_scope(self._sessions) as session:
            item, collection_id = await self._authorized_item(
                session, access, item_id, missing="item not found"
            )
            payloads = await self._indexed_payloads(
                access,
                item_id=str(item.id),
                collection_item_id=str(collection_id),
                chunk_id=chunk_id,
                limit=1 if chunk_id else VIEWER_CHUNK_LIMIT,
            )
            citations = await CitationService(session).get_for_chunks(
                item.id,
                [_chunk_identity(item.id, payload) for payload in payloads],
            )
            elements, chunks_by_id = viewer_elements(
                str(item.id), payloads, citations
            )
            focus, focus_citation = self._focus(
                item.id, chunk_id, chunks_by_id, citations
            )
            return {
                "item_id": str(item.id),
                "title": item.title,
                "content_type": item.mime_type or "text/plain",
                "status": item.status,
                "external_url": CitationResolver.original_url(
                    self._presenter.source_identity(item), focus_citation
                ),
                "document_url": (
                    self._presenter.presigned_url(item) if chunk_id else None
                ),
                "preview": self._presenter.preview_payload(item),
                "elements": elements,
                "focus": focus,
            }

    async def get_workspace_home(self, access: AuthContext) -> dict[str, Any]:
        """Return the caller's governed Collection home without leaking Items."""

        tenant_id = require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with session_scope(self._sessions) as session:
            access_service = CollectionAccessService(session)
            collection_ids = await access_service.allowed_collection_ids(access)
            if not collection_ids:
                return {
                    "items": [],
                    "total": 0,
                    "recent_documents": [],
                    "personal_collection_id": None,
                }
            collections = list(
                await session.scalars(
                    select(Item)
                    .where(
                        Item.id.in_(collection_ids),
                        Item.tenant_id == tenant_id,
                        Item.item_type == "collection",
                        Item.status != "deleted",
                        Item.deleted_at.is_(None),
                    )
                    .order_by(Item.title, Item.id)
                )
            )
            document_counts, source_counts = await self._collection_counts(
                session, collection_ids
            )
            recent_documents = list(
                await session.scalars(
                    self._document_statement(
                        tenant_id=tenant_id,
                        collection_ids=collection_ids,
                    )
                    .order_by(Item.updated_at.desc(), Item.id)
                    .limit(8)
                )
            )
        personal_collection_id = next(
            (
                str(item.id)
                for item in collections
                if item.created_by_user_id == access.user_id
                and str(item.metadata_.get("system_kind") or "")
                in {"personal_uploads", "conversation_artifacts"}
            ),
            None,
        )
        return {
            "items": [
                _collection_payload(
                    item,
                    document_count=document_counts.get(item.id, 0),
                    source_count=source_counts.get(item.id, 0),
                )
                for item in collections
            ],
            "total": len(collections),
            "recent_documents": [_document_payload(item) for item in recent_documents],
            "personal_collection_id": personal_collection_id,
        }

    async def get_collection_workspace(
        self,
        access: AuthContext,
        *,
        collection_id: UUID,
        search: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """Return direct child Items only after collection access is confirmed."""

        tenant_id = require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with session_scope(self._sessions) as session:
            access_service = CollectionAccessService(session)
            collection = await access_service.require_item_access(
                collection_id, access=access
            )
            if collection.item_type != "collection":
                raise DocumentNotFoundError("collection not found")
            allowed_ids = await access_service.allowed_collection_ids(access)
            document_counts, source_counts = await self._collection_counts(
                session, (collection.id,)
            )
            child_collections = list(
                await session.scalars(
                    select(Item)
                    .where(
                        Item.tenant_id == tenant_id,
                        Item.item_type == "collection",
                        Item.parent_item_id == collection.id,
                        Item.id.in_(allowed_ids),
                        Item.status != "deleted",
                        Item.deleted_at.is_(None),
                    )
                    .order_by(Item.title, Item.id)
                )
            )
            child_counts, child_source_counts = await self._collection_counts(
                session, tuple(item.id for item in child_collections)
            )
            document_filters = [
                Item.tenant_id == tenant_id,
                Item.item_type == "document",
                Item.parent_item_id == collection.id,
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            ]
            normalized_search = (search or "").strip()
            if normalized_search:
                document_filters.append(Item.title.ilike(f"%{normalized_search}%"))
            total = await session.scalar(
                select(func.count()).select_from(Item).where(*document_filters)
            )
            documents = list(
                await session.scalars(
                    self._document_statement(
                        tenant_id=tenant_id,
                        collection_ids=(collection.id,),
                        filters=document_filters,
                    )
                    .order_by(Item.updated_at.desc(), Item.id)
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
        return {
            "collection": _collection_payload(
                collection,
                document_count=document_counts.get(collection.id, 0),
                source_count=source_counts.get(collection.id, 0),
            ),
            "child_collections": [
                _collection_payload(
                    item,
                    document_count=child_counts.get(item.id, 0),
                    source_count=child_source_counts.get(item.id, 0),
                )
                for item in child_collections
            ],
            "documents": [_document_payload(item) for item in documents],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def _authorized_item(
        self,
        session: AsyncSession,
        access: AuthContext,
        item_id: str,
        *,
        missing: str,
    ) -> tuple[Any, UUID]:
        item = await ItemService(session).get_item_by_canonical_id(
            item_id, access=access
        )
        if access.tenant_id is None:
            raise DocumentNotFoundError(missing)
        collection_id = await CollectionAccessService(
            session
        ).authorization_collection_id(item.id, tenant_id=access.tenant_id)
        if collection_id is None:
            raise DocumentNotFoundError(missing)
        return item, collection_id

    async def _indexed_payloads(
        self,
        access: AuthContext,
        *,
        item_id: str,
        collection_item_id: str,
        chunk_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if access.tenant_id is None:
            return []
        chunks = await self._index.get_item_content(
            item_id,
            tenant_id=str(access.tenant_id),
            collection_item_id=collection_item_id,
            chunk_id=chunk_id,
            limit=limit,
        )
        return [
            {
                "item_id": chunk.item_id,
                "chunk_id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "title": chunk.title,
                "content_type": chunk.content_type,
                "chunk_text": chunk.chunk_text,
                "section_path": list(chunk.context.section_path),
                "citation_anchor": chunk.citation.anchor,
                "page_start": chunk.citation.page_start,
                "page_end": chunk.citation.page_end,
            }
            for chunk in chunks
        ]

    @staticmethod
    def _document_statement(
        *,
        tenant_id: UUID,
        collection_ids: tuple[UUID, ...],
        filters: list[Any] | None = None,
    ) -> Any:
        return (
            select(Item)
            .options(
                selectinload(Item.external_resources)
                .selectinload(ExternalResource.ingestion_source)
                .selectinload(IngestionSource.integration_connection)
            )
            .where(
                *(filters or [
                    Item.tenant_id == tenant_id,
                    Item.item_type == "document",
                    Item.parent_item_id.in_(collection_ids),
                    Item.status != "deleted",
                    Item.deleted_at.is_(None),
                ])
            )
        )

    @staticmethod
    async def _collection_counts(
        session: AsyncSession,
        collection_ids: tuple[UUID, ...],
    ) -> tuple[dict[UUID, int], dict[UUID, int]]:
        if not collection_ids:
            return {}, {}
        active_documents = (
            Item.parent_item_id.in_(collection_ids),
            Item.item_type == "document",
            Item.status != "deleted",
            Item.deleted_at.is_(None),
        )
        document_counts = {
            collection_id: int(count)
            for collection_id, count in (
                await session.execute(
                    select(Item.parent_item_id, func.count(Item.id))
                    .where(*active_documents)
                    .group_by(Item.parent_item_id)
                )
            ).all()
            if collection_id is not None
        }
        source_counts = {
            collection_id: int(count)
            for collection_id, count in (
                await session.execute(
                    select(
                        Item.parent_item_id,
                        func.count(distinct(ExternalResource.ingestion_source_id)),
                    )
                    .join(ExternalResource, ExternalResource.item_id == Item.id)
                    .where(*active_documents, ExternalResource.deleted_at.is_(None))
                    .group_by(Item.parent_item_id)
                )
            ).all()
            if collection_id is not None
        }
        return document_counts, source_counts

    @staticmethod
    def _focus(
        item_id: UUID,
        chunk_id: str | None,
        chunks_by_id: dict[str, dict[str, Any]],
        citations: dict[str, CitationInfo],
    ) -> tuple[dict[str, Any] | None, CitationInfo]:
        if not chunk_id:
            return None, CitationInfo()
        payload = chunks_by_id.get(chunk_id)
        if payload is None:
            raise DocumentNotFoundError("citation not found")
        citation = citations.get(_chunk_identity(item_id, payload))
        if citation is None:
            raise DocumentNotFoundError("citation not found")
        return (
            {
                "chunk_id": chunk_id,
                "chunk_text": str(payload.get("chunk_text") or ""),
                "citation": citation,
            },
            citation,
        )


def _chunk_identity(item_id: UUID, payload: dict[str, Any]) -> str:
    return str(
        payload.get("chunk_id")
        or f"{item_id}:{int(payload.get('chunk_index') or 0)}"
    )


def _collection_payload(
    item: Item,
    *,
    document_count: int,
    source_count: int,
) -> dict[str, Any]:
    description = item.metadata_.get("description")
    return {
        "id": str(item.id),
        "title": item.title,
        "description": description if isinstance(description, str) else None,
        "parent_item_id": str(item.parent_item_id) if item.parent_item_id else None,
        "document_count": document_count,
        "source_count": source_count,
        "updated_at": item.updated_at.isoformat(),
    }


def _document_payload(item: Item) -> dict[str, Any]:
    resource = next(
        (candidate for candidate in item.external_resources if candidate.deleted_at is None),
        None,
    )
    source = None
    if resource is not None:
        connection = resource.ingestion_source.integration_connection
        source = {
            "display_name": connection.display_name,
            "connector_key": connection.connector_key,
            "source_url": resource.source_url,
        }
    return {
        "id": str(item.id),
        "title": item.title,
        "content_type": item.mime_type,
        "document_type": item.document_type,
        "status": item.status,
        "updated_at": item.updated_at.isoformat(),
        "source": source,
    }


__all__ = ["KnowledgeViewService"]
