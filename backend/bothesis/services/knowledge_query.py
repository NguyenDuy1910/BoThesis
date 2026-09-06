"""Permission-filtered semantic search over indexed Collection content."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from bothesis.agent.models import AgentContext
from bothesis.db.engine import SessionFactory, session_scope
from bothesis.knowledge import ItemKnowledgeRetriever
from bothesis.services import (
    KNOWLEDGE_READ_PERMISSION,
    AuthContext,
    require_tenant_permission,
)
from bothesis.services.collection_access import CollectionAccessService


class KnowledgeQueryService:
    """Search only the Collections the caller is authorized to read."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        retriever: ItemKnowledgeRetriever,
    ) -> None:
        self._sessions = session_factory
        self._retriever = retriever

    async def search(
        self,
        access: AuthContext,
        *,
        query: str,
        top_k: int,
        collection_item_ids: Sequence[UUID] | None,
    ) -> dict[str, Any]:
        """Return ranked evidence with its citation and source lineage."""

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with session_scope(self._sessions) as session:
            allowed_ids = await CollectionAccessService(session).allowed_collection_ids(
                access
            )
        requested_ids = tuple(dict.fromkeys(collection_item_ids or allowed_ids))
        if not set(requested_ids).issubset(set(allowed_ids)):
            raise PermissionError("one or more selected Collections are unavailable")
        if access.tenant_id is None or not requested_ids:
            return {"results": [], "total": 0}
        evidence = await self._retriever.search(
            query,
            limit=top_k,
            ctx=AgentContext(
                user_id=str(access.user_id),
                tenant_id=str(access.tenant_id),
                roles=[access.role_code] if access.role_code else [],
                collection_item_ids=tuple(str(value) for value in requested_ids),
            ),
        )
        results = [
            _result_payload(item)
            for item in evidence
            if item.collection_item_id is not None
        ]
        return {"results": results, "total": len(results)}


def _result_payload(item: Any) -> dict[str, Any]:
    return {
        "id": item.item_id,
        "collection_item_id": item.collection_item_id,
        "title": item.title,
        "excerpt": item.content,
        "score": (
            item.rerank_score
            if item.rerank_score is not None
            else item.relevance_score or 0.0
        ),
        "url": item.source.url if item.source is not None else None,
        "metadata": {
            "chunk_id": item.chunk_id,
            "section_path": list(item.section_path),
            "citation": item.citation.model_dump(mode="json", exclude_none=True),
            "source": (
                item.source.model_dump(mode="json", exclude_none=True)
                if item.source is not None
                else None
            ),
        },
    }


__all__ = ["KnowledgeQueryService"]
