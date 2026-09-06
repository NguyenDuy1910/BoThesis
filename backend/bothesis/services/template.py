"""Document templates: Knowledge Base content the agent may start a document from."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select

from bothesis.agent.models import AgentContext
from bothesis.db.engine import SessionFactory
from bothesis.db.models import Item
from bothesis.knowledge import KnowledgeRetriever
from bothesis.services import (
    KNOWLEDGE_READ_PERMISSION,
    TEMPLATE_LIBRARY_METADATA_KEY,
    AuthContext,
    require_tenant_permission,
)
from bothesis.services.collection_access import CollectionAccessService
from bothesis.services.identity_store import resolve_agent_access

_EXCERPT_CHARACTERS = 320


class TemplateService:
    """Find the templates a caller may read and the libraries they may use.

    A template is any document inside a Collection flagged as a template
    library (``metadata.template_library``). Search goes through the same
    permission-scoped retriever as every other knowledge lookup, restricted to
    those libraries, so a result is always access-permitted, indexed content.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        retriever: KnowledgeRetriever,
        result_limit: int = 5,
    ) -> None:
        if result_limit < 1:
            raise ValueError("result_limit must be at least one")
        self._sessions = session_factory
        self._retriever = retriever
        self._result_limit = result_limit

    async def resolve_access(self, scope: AgentContext) -> AuthContext:
        """Re-resolve the authenticated caller behind an agent tool call."""

        return await resolve_agent_access(
            self._sessions, user_id=scope.user_id, tenant_id=scope.tenant_id
        )

    async def library_collections(self, access: AuthContext) -> list[dict[str, Any]]:
        """The template libraries the caller can read, for search and publishing."""

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with self._sessions() as session:
            allowed = await CollectionAccessService(session).allowed_collection_ids(access)
            if not allowed:
                return []
            rows = await session.execute(
                select(Item.id, Item.title)
                .where(
                    Item.id.in_(allowed),
                    Item.item_type == "collection",
                    Item.status != "deleted",
                    Item.deleted_at.is_(None),
                    Item.metadata_[TEMPLATE_LIBRARY_METADATA_KEY].as_boolean().is_(True),
                )
                .order_by(Item.title, Item.id)
            )
        return [{"id": str(item_id), "title": title} for item_id, title in rows.all()]

    async def search(
        self, access: AuthContext, queries: Sequence[str]
    ) -> list[dict[str, Any]]:
        """Return the best-matching templates, one entry per document."""

        tenant_id = require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        libraries = await self.library_collections(access)
        normalized = [" ".join(query.split()) for query in queries]
        normalized = [query for query in normalized if query]
        if not libraries or not normalized:
            return []
        titles = {library["id"]: library["title"] for library in libraries}
        ctx = AgentContext(
            user_id=str(access.user_id),
            tenant_id=str(tenant_id),
            roles=[access.role_code] if access.role_code else [],
            collection_item_ids=tuple(titles),
        )
        best: dict[str, dict[str, Any]] = {}
        for query in normalized:
            for evidence in await self._retriever.search(
                query, limit=self._result_limit, ctx=ctx
            ):
                score = (
                    evidence.rerank_score
                    if evidence.rerank_score is not None
                    else evidence.relevance_score or 0.0
                )
                existing = best.get(evidence.item_id)
                if existing is not None and existing["score"] >= score:
                    continue
                best[evidence.item_id] = {
                    "id": evidence.item_id,
                    "title": evidence.title,
                    "collection_id": evidence.collection_item_id,
                    "collection_title": titles.get(evidence.collection_item_id or ""),
                    "excerpt": evidence.content[:_EXCERPT_CHARACTERS],
                    "score": score,
                }
        ranked = sorted(best.values(), key=lambda entry: entry["score"], reverse=True)
        return ranked[: self._result_limit]


__all__ = ["TemplateService"]
