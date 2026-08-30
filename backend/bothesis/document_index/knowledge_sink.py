"""Persist connector output as canonical Items and project Documents to Qdrant."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from qdrant_client import models as qmodels
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from bothesis.connector.protocol import AnyItem, Chunk, CollectionItem, DocumentItem, DocumentKind
from bothesis.db.models import Item, ExternalResource, IngestionSource
from bothesis.document_index import (
    BM25_MODEL,
    BM25_OPTIONS,
    DENSE_VECTOR_NAME,
    EmbeddingService,
    SPARSE_VECTOR_NAME,
)
from bothesis.document_index.payload import QdrantPayloadContext, build_qdrant_records
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer
from bothesis.document_index.vector_store import VectorStore
from bothesis.services.preview import KnowledgePreviewService

log = logging.getLogger(__name__)


class QdrantKnowledgeSink:
    """Ingestion sink at the connector-to-knowledge dependency boundary."""

    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingService,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ingestion_source_id: UUID,
        embedding_batch_size: int = 32,
        semantic_contextualizer: SemanticContextualizer | None = None,
        preview_service: KnowledgePreviewService | None = None,
    ) -> None:
        if embedding_batch_size < 1:
            raise ValueError("embedding_batch_size must be at least one")
        self._store = store
        self._embedder = embedder
        self._session_factory = session_factory
        self._ingestion_source_id = ingestion_source_id
        self._embedding_batch_size = embedding_batch_size
        self._semantic_contextualizer = semantic_contextualizer
        self._preview_service = preview_service

    async def write_item(
        self,
        item: AnyItem,
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> UUID:
        self._validate_source(item, tenant_id=tenant_id, integration_connection_id=connector_id)
        stored, _, _ = await self._persist_item(item)
        return stored.id

    async def write(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> int:
        normalized_tenant = self._validate_source(
            item, tenant_id=tenant_id, integration_connection_id=connector_id
        )
        stored, source, _ = await self._persist_item(item, status="processing")
        await self._persist_preview(stored)
        canonical_item, canonical_chunks = self._canonical_document(item, chunks, stored)
        records = (
            await build_qdrant_records(
                canonical_chunks,
                canonical_item,
                QdrantPayloadContext(
                    tenant_id=normalized_tenant,
                    integration_connection_id=str(source.integration_connection_id),
                    ingestion_source_id=str(source.id),
                    collection_item_id=str(source.target_item_id),
                    parent_item_id=(str(stored.parent_item_id) if stored.parent_item_id else None),
                    document_type=stored.document_type or "plain_text",
                    connector_key=source.integration_connection.connector_key,
                    embedding_model=self._embedder.embedding_model,
                ),
                semantic_contextualizer=self._semantic_contextualizer,
            )
            if canonical_chunks
            else []
        )
        await self._soft_delete_points(tenant_id=normalized_tenant, item_id=str(stored.id))
        if not records:
            await self._set_item_status(stored.id, "ready")
            return 0
        vectors: list[list[float]] = []
        texts = [record.payload.contextual_text for record in records]
        for start in range(0, len(texts), self._embedding_batch_size):
            vectors.extend(
                await self._embedder.embed_documents(
                    texts[start : start + self._embedding_batch_size]
                )
            )
        if len(vectors) != len(records) or any(not vector for vector in vectors):
            await self._set_item_status(stored.id, "failed")
            raise ValueError("every contextual chunk requires one embedding")
        try:
            await self._store.upsert_points(
                [
                    qmodels.PointStruct(
                        id=record.point_id,
                        vector={
                            DENSE_VECTOR_NAME: vector,
                            SPARSE_VECTOR_NAME: qmodels.Document(
                                text=record.payload.contextual_text,
                                model=BM25_MODEL,
                                options=BM25_OPTIONS,
                            ),
                        },
                        payload=record.payload.for_qdrant(),
                    )
                    for record, vector in zip(records, vectors, strict=True)
                ]
            )
        except Exception:
            await self._set_item_status(stored.id, "failed")
            raise
        await self._set_item_status(stored.id, "ready")
        return len(records)

    async def soft_delete_item(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        item_id: str,
    ) -> None:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be blank")
        async with self._session_factory.begin() as session:
            source = await session.scalar(
                select(IngestionSource)
                .options(joinedload(IngestionSource.integration_connection))
                .where(IngestionSource.id == self._ingestion_source_id)
            )
            if source is None or str(source.integration_connection_id) != str(connector_id):
                raise ValueError(
                    "ingestion source connection does not match the delete request"
                )
            from bothesis.services import ItemService

            stored = await ItemService(session).soft_delete_external_resource(source.id, item_id)
            canonical_id = stored.id if stored is not None else None
        if canonical_id is not None:
            await self._soft_delete_points(
                tenant_id=normalized_tenant, item_id=str(canonical_id)
            )

    async def _persist_item(
        self, item: AnyItem, *, status: str | None = None
    ) -> tuple[Item, IngestionSource, ExternalResource]:
        from bothesis.services import ItemService

        original = item.original if isinstance(item, DocumentItem) else None
        metadata = {
            **{
                key: value
                for key, value in item.metadata.items()
                if key not in {"preview", "processing", "storage"}
            },
            "source": item.source.model_dump(mode="json", exclude_none=True),
            "external_hierarchy": item.hierarchy.model_dump(mode="json", exclude_none=True),
        }
        if original is not None:
            metadata["storage"] = original.model_dump(mode="json", exclude_none=True)
        async with self._session_factory.begin() as session:
            source = await session.scalar(
                select(IngestionSource)
                .options(
                    joinedload(IngestionSource.integration_connection),
                    joinedload(IngestionSource.target_item),
                )
                .where(IngestionSource.id == self._ingestion_source_id)
            )
            if source is None:
                raise ValueError(
                    f"ingestion source not found: {self._ingestion_source_id}"
                )
            stored = await ItemService(session).upsert_ingested_item(
                source.id,
                item.source.external_id,
                canonical_external_id=item.id,
                item_type=item.type,
                title=item.title,
                document_type=(
                    self._document_type(
                        item, source.integration_connection.connector_key
                    )
                    if isinstance(item, DocumentItem)
                    else None
                ),
                parent_external_id=item.hierarchy.parent_id,
                parent_relation=self._parent_relation(item),
                source_url=item.source.url,
                external_version=item.source.external_version,
                etag=item.source.etag,
                external_updated_at=item.updated_at,
                mime_type=(
                    original.content_type if original is not None else self._mime_type(item)
                ),
                size_bytes=original.size_bytes if original is not None else None,
                metadata=metadata,
                storage_key=original.key if original is not None else None,
                status=status or "ready",
            )
            external_resource = await session.scalar(
                select(ExternalResource).where(
                    ExternalResource.ingestion_source_id == source.id,
                    ExternalResource.external_id == item.source.external_id,
                )
            )
            if external_resource is None:
                raise RuntimeError("external resource was not stored")
            session.expunge(stored)
            session.expunge(source)
            session.expunge(external_resource)
            return stored, source, external_resource

    async def _persist_preview(self, stored: Item) -> None:
        if self._preview_service is None or not stored.storage_key:
            return
        try:
            manifest = await self._preview_service.generate(stored)
            if manifest is None:
                return
            preview_metadata = manifest.model_dump(mode="json")
            if stored.metadata_.get("preview") == preview_metadata:
                return
            from bothesis.services import ItemService

            async with self._session_factory.begin() as session:
                await ItemService(session).merge_metadata(
                    stored.id,
                    {"preview": preview_metadata},
                )
            stored.metadata_ = {
                **dict(stored.metadata_),
                "preview": preview_metadata,
            }
        except Exception as exc:
            log.warning(
                "knowledge preview generation failed item_id=%s error_type=%s",
                stored.id,
                type(exc).__name__,
            )

    async def _set_item_status(self, item_id: UUID, status: str) -> None:
        from bothesis.services import ItemService

        async with self._session_factory.begin() as session:
            service = ItemService(session)
            if status == "ready":
                await service.mark_ready(item_id)
            else:
                await service.mark_failed(item_id)

    async def _soft_delete_points(self, *, tenant_id: str, item_id: str) -> None:
        await self._store.set_payload(
            payload={"is_deleted": True},
            points=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="tenant_id", match=qmodels.MatchValue(value=tenant_id)
                    ),
                    qmodels.FieldCondition(
                        key="item_id", match=qmodels.MatchValue(value=item_id)
                    ),
                ]
            ),
        )

    @staticmethod
    def _canonical_document(
        item: DocumentItem, chunks: Sequence[Chunk], stored: Item
    ) -> tuple[DocumentItem, tuple[Chunk, ...]]:
        canonical_id = str(stored.id)
        hierarchy = item.hierarchy.model_copy(
            update={
                "parent_id": str(stored.parent_item_id) if stored.parent_item_id else None,
                "root_id": None,
                "ancestor_ids": [],
            }
        )
        canonical_item = item.model_copy(update={"id": canonical_id, "hierarchy": hierarchy})
        canonical_chunks = tuple(
            chunk.model_copy(
                update={"id": f"{canonical_id}:{chunk.chunk_index}", "item_id": canonical_id}
            )
            for chunk in chunks
        )
        return canonical_item, canonical_chunks

    @staticmethod
    def _validate_source(
        item: AnyItem, *, tenant_id: str, integration_connection_id: str | int
    ) -> str:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be blank")
        if str(item.source.connector_id) != str(integration_connection_id):
            raise ValueError(
                "item source integration connection does not match the index request"
            )
        return normalized_tenant

    @staticmethod
    def _document_type(item: DocumentItem, connector_key: str) -> str:
        if item.document_kind == DocumentKind.PAGE:
            return "confluence_page" if connector_key == "confluence" else "web_page"
        return {
            DocumentKind.PDF: "pdf",
            DocumentKind.DOCUMENT: "word_document",
            DocumentKind.IMAGE: "image",
            DocumentKind.ISSUE: "jira_issue",
            DocumentKind.MESSAGE: "plain_text",
            DocumentKind.EMAIL: "email",
            DocumentKind.NOTE: "plain_text",
            DocumentKind.WEB_PAGE: "web_page",
            DocumentKind.RECORD: "plain_text",
        }.get(item.document_kind, "plain_text")

    @staticmethod
    def _mime_type(item: DocumentItem) -> str | None:
        if item.document_kind == DocumentKind.PDF:
            return "application/pdf"
        if item.document_kind == DocumentKind.IMAGE:
            return "image/*"
        if item.document_kind in {DocumentKind.PAGE, DocumentKind.WEB_PAGE}:
            return "text/html"
        return None

    @staticmethod
    def _parent_relation(item: AnyItem) -> str:
        relation = item.metadata.get("parent_relation")
        if isinstance(relation, str) and relation in {
            "contains", "child", "attachment", "embedded"
        }:
            return relation
        if isinstance(item, CollectionItem):
            return "contains"
        if item.metadata.get("attachment_id") or item.metadata.get("file_name"):
            return "attachment"
        return "child"

    async def aclose(self) -> None:
        await self._store.aclose()


__all__ = ["QdrantKnowledgeSink"]
