"""Resolve citations and document viewers from indexed, authorized content."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.connector.protocol import CitationInfo
from bothesis.db.engine import SessionFactory, session_scope
from bothesis.document_index import ItemIndex
from bothesis.knowledge import CitationResolver
from bothesis.services import AuthContext, DocumentNotFoundError
from bothesis.services.citation import CitationService
from bothesis.services.collection_access import CollectionAccessService
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


__all__ = ["KnowledgeViewService"]
