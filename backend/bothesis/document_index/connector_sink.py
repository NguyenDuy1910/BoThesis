"""Persist connector Items and project document chunks directly to Qdrant."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from qdrant_client import models as qmodels
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.connector.protocol import (
    AccessEffect,
    AnyItem,
    Chunk,
    CollectionItem,
    DocumentItem,
    DocumentKind,
    FileItem,
)
from bothesis.document_index import (
    BM25_MODEL,
    BM25_OPTIONS,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
)
from bothesis.document_index.embedding import EmbeddingService
from bothesis.document_index.payload import QdrantPayloadContext, build_qdrant_records
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer
from bothesis.document_index.vector_store import VectorStore


class QdrantConnectorIndexSink:
    """Store Item metadata in PostgreSQL and retry-safe retrieval points in Qdrant."""

    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingService,
        *,
        embedding_batch_size: int = 32,
        semantic_contextualizer: SemanticContextualizer | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        connector_scope_id: int | None = None,
    ) -> None:
        if embedding_batch_size < 1:
            raise ValueError("embedding_batch_size must be at least one")
        if (session_factory is None) != (connector_scope_id is None):
            raise ValueError(
                "session_factory and connector_scope_id must be supplied together"
            )
        self._store = store
        self._embedder = embedder
        self._embedding_batch_size = embedding_batch_size
        self._semantic_contextualizer = semantic_contextualizer
        self._session_factory = session_factory
        self._connector_scope_id = connector_scope_id

    async def write_item(
        self,
        item: AnyItem,
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> UUID | None:
        """Persist a Collection, Document, or opaque File without indexing it."""

        self._validate_source(item, tenant_id=tenant_id, connector_id=connector_id)
        return await self._persist_item(item, connector_id=int(connector_id))

    async def write(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> int:
        normalized_tenant = self._validate_source(
            item, tenant_id=tenant_id, connector_id=connector_id
        )
        numeric_connector_id = int(connector_id)
        canonical_item, canonical_chunks = _canonical_document(
            item, chunks, connector_id=numeric_connector_id
        )
        records = (
            await build_qdrant_records(
                canonical_chunks,
                canonical_item,
                QdrantPayloadContext(
                    tenant_id=normalized_tenant,
                    connector_id=numeric_connector_id,
                    scope_id=self._connector_scope_id,
                    embedding_model=self._embedder.model,
                    denied_reader_ids=_denied_principal_tokens(item),
                ),
                semantic_contextualizer=self._semantic_contextualizer,
            )
            if canonical_chunks
            else []
        )
        item_id = await self._persist_item(
            item, connector_id=numeric_connector_id, status="processing"
        )
        if not canonical_chunks:
            await self._soft_delete_points(
                tenant_id=normalized_tenant,
                connector_id=numeric_connector_id,
                item_id=str(canonical_item.id),
            )
            if item_id is not None:
                await self._mark_ready(item_id)
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
            if item_id is not None:
                await self._mark_failed(item_id)
            raise ValueError("every contextual chunk requires one embedding")

        await self._soft_delete_points(
            tenant_id=normalized_tenant,
            connector_id=numeric_connector_id,
            item_id=str(canonical_item.id),
        )
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
            if item_id is not None:
                await self._mark_failed(item_id)
            raise
        if item_id is not None:
            await self._mark_ready(item_id)
        return len(records)

    async def soft_delete_item(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        item_id: str,
    ) -> None:
        from bothesis.services import ItemService

        normalized_tenant = tenant_id.strip()
        numeric_connector_id = int(connector_id)
        canonical_id = ItemService.connector_item_id(numeric_connector_id, item_id)
        if not normalized_tenant:
            raise ValueError("tenant_id must not be blank")
        await self._soft_delete_points(
            tenant_id=normalized_tenant,
            connector_id=numeric_connector_id,
            item_id=str(canonical_id),
        )
        if self._session_factory is not None:
            async with self._session_factory.begin() as session:
                await ItemService(session).soft_delete_external_item(
                    numeric_connector_id, item_id
                )

    async def _soft_delete_points(
        self,
        *,
        tenant_id: str,
        connector_id: int,
        item_id: str,
    ) -> None:
        await self._store.set_payload(
            payload={
                "is_deleted": True,
                "reader_ids": [],
                "denied_reader_ids": [],
            },
            points=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="tenant_id", match=qmodels.MatchValue(value=tenant_id)
                    ),
                    qmodels.FieldCondition(
                        key="connector_id", match=qmodels.MatchValue(value=connector_id)
                    ),
                    qmodels.FieldCondition(
                        key="item_id", match=qmodels.MatchValue(value=item_id)
                    ),
                ]
            ),
        )

    async def _persist_item(
        self,
        item: AnyItem,
        *,
        connector_id: int,
        status: str | None = None,
    ) -> UUID | None:
        if self._session_factory is None:
            return None
        from bothesis.services import ItemService

        assert self._connector_scope_id is not None
        original = item.original if isinstance(item, (DocumentItem, FileItem)) else None
        metadata = {
            **dict(item.metadata),
            "source": item.source.model_dump(mode="json", exclude_none=True),
            "hierarchy": item.hierarchy.model_dump(mode="json", exclude_none=True),
        }
        async with self._session_factory.begin() as session:
            stored = await ItemService(session).upsert_external_item(
                self._connector_scope_id,
                item.source.external_id,
                canonical_source_id=item.id,
                item_type=item.type,
                title=item.title,
                document_kind=(
                    item.document_kind.value if isinstance(item, DocumentItem) else None
                ),
                collection_kind=(
                    item.collection_kind.value if isinstance(item, CollectionItem) else None
                ),
                parent_source_id=item.hierarchy.parent_id,
                source_url=item.source.url,
                external_version=item.source.external_version,
                etag=item.source.etag,
                external_updated_at=item.updated_at,
                mime_type=(
                    original.content_type if original is not None else _document_mime_type(item)
                ),
                size_bytes=original.size_bytes if original is not None else None,
                metadata=metadata,
                storage_key=original.key if original is not None else None,
                content_sha256=(original.checksum_sha256 if original is not None else None),
                allowed_principal_tokens=item.access.to_reader_ids(),
                denied_principal_tokens=_denied_principal_tokens(item),
                status=status or ("unsupported" if isinstance(item, FileItem) else "ready"),
            )
            return stored.id

    async def _mark_ready(self, item_id: UUID) -> None:
        from bothesis.services import ItemService

        assert self._session_factory is not None
        async with self._session_factory.begin() as session:
            await ItemService(session).mark_ready(item_id)

    async def _mark_failed(self, item_id: UUID) -> None:
        from bothesis.services import ItemService

        assert self._session_factory is not None
        async with self._session_factory.begin() as session:
            await ItemService(session).mark_failed(item_id)

    @staticmethod
    def _validate_source(
        item: AnyItem, *, tenant_id: str, connector_id: str | int
    ) -> str:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be blank")
        if str(item.source.connector_id) != str(connector_id):
            raise ValueError("item source connector does not match the index request")
        return normalized_tenant

    async def aclose(self) -> None:
        await self._store.aclose()


def _canonical_document(
    item: DocumentItem,
    chunks: Sequence[Chunk],
    *,
    connector_id: int,
) -> tuple[DocumentItem, tuple[Chunk, ...]]:
    from bothesis.services import ItemService

    canonical_id = str(ItemService.connector_item_id(connector_id, item.id))
    hierarchy = item.hierarchy.model_copy(
        update={
            "parent_id": (
                str(ItemService.connector_item_id(connector_id, item.hierarchy.parent_id))
                if item.hierarchy.parent_id
                else None
            ),
            "root_id": (
                str(ItemService.connector_item_id(connector_id, item.hierarchy.root_id))
                if item.hierarchy.root_id
                else None
            ),
            "ancestor_ids": [
                str(ItemService.connector_item_id(connector_id, value))
                for value in item.hierarchy.ancestor_ids
            ],
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


def _document_mime_type(item: AnyItem) -> str | None:
    if not isinstance(item, DocumentItem):
        return getattr(item, "media_type", None)
    if item.document_kind == DocumentKind.PDF:
        return "application/pdf"
    if item.document_kind == DocumentKind.IMAGE:
        return "image/*"
    if item.document_kind == DocumentKind.WEB_PAGE:
        return "text/html"
    return None


def _denied_principal_tokens(item: AnyItem) -> list[str]:
    values: list[str] = []
    for rule in item.access.direct.rules:
        if rule.effect != AccessEffect.DENY:
            continue
        principal = rule.principal
        values.append(
            principal.id
            if principal.type == "public" or principal.id.startswith(f"{principal.type}:")
            else f"{principal.type}:{principal.id}"
        )
    return values


__all__ = ["QdrantConnectorIndexSink"]
