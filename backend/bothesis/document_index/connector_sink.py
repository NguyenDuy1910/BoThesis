"""Durable connector output and its derived Qdrant projection."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from qdrant_client import models as qmodels
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.connector.protocol import (
    AccessEffect,
    Chunk,
    DocumentItem,
    DocumentKind,
)
from bothesis.document_index.embedding import EmbeddingService
from bothesis.document_index.payload import QdrantPayloadContext, build_qdrant_records
from bothesis.document_index.vector_store import VectorStore


class QdrantConnectorIndexSink:
    """Persist canonical connector evidence, then build its retrieval index.

    Supplying ``session_factory``, ``connector_scope_id``, and ``generation``
    enables the production snapshot path. New-generation points remain
    tombstoned until :meth:`activate_generation` switches the scope, so a
    partial sync cannot leak through retrieval.
    """

    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingService,
        *,
        embedding_batch_size: int = 32,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        connector_scope_id: int | None = None,
        generation: int | None = None,
    ) -> None:
        if embedding_batch_size < 1:
            raise ValueError("embedding_batch_size must be at least one")
        persistence_values = (session_factory, connector_scope_id, generation)
        if any(value is not None for value in persistence_values) and not all(
            value is not None for value in persistence_values
        ):
            raise ValueError(
                "session_factory, connector_scope_id, and generation must be supplied together"
            )
        if generation is not None and generation < 1:
            raise ValueError("generation must be at least one")
        self._store = store
        self._embedder = embedder
        self._embedding_batch_size = embedding_batch_size
        self._session_factory = session_factory
        self._connector_scope_id = connector_scope_id
        self._generation = generation

    async def write(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> int:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be blank")
        if str(item.source.connector_id) != str(connector_id):
            raise ValueError("item source connector does not match the index request")
        records = (
            build_qdrant_records(
                chunks,
                item,
                QdrantPayloadContext(
                    tenant_id=normalized_tenant,
                    connector_id=connector_id,
                    scope_id=self._connector_scope_id,
                    generation=self._generation,
                    is_deleted=self._generation is not None,
                    embedding_model=self._embedder.model,
                ),
            )
            if chunks
            else []
        )
        document_id = await self._persist_canonical(
            item,
            chunks,
            tenant_id=normalized_tenant,
        )
        if not chunks:
            await self._soft_delete_points(
                tenant_id=normalized_tenant,
                connector_id=connector_id,
                item_id=item.id,
            )
            if document_id is not None:
                await self._mark_indexed(document_id, allow_empty=True)
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
            raise ValueError("every contextual chunk requires one embedding")
        # Complete all fallible source projection and embedding work before
        # tombstoning the prior point set. This minimizes the replacement
        # window while still removing stale trailing chunks.
        await self._soft_delete_points(
            tenant_id=normalized_tenant,
            connector_id=connector_id,
            item_id=item.id,
        )
        try:
            await self._store.upsert_points(
                [
                    qmodels.PointStruct(
                        id=record.point_id,
                        vector={"content": vector},
                        payload=record.payload.for_qdrant(),
                    )
                    for record, vector in zip(records, vectors, strict=True)
                ]
            )
        except Exception:
            if document_id is not None:
                await self._mark_failed(document_id)
            raise
        if document_id is not None:
            await self._mark_indexed(document_id)
        return len(records)

    async def soft_delete_item(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        item_id: str,
    ) -> None:
        normalized_tenant = tenant_id.strip()
        normalized_item = item_id.strip()
        if not normalized_tenant or not normalized_item:
            raise ValueError("tenant_id and item_id must not be blank")
        await self._soft_delete_points(
            tenant_id=normalized_tenant,
            connector_id=connector_id,
            item_id=normalized_item,
        )

    async def activate_generation(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> None:
        """Expose this completed scope generation to retrieval."""

        if self._connector_scope_id is None or self._generation is None:
            raise RuntimeError("generation activation requires a persistent sink")
        base = [
            qmodels.FieldCondition(
                key="tenant_id",
                match=qmodels.MatchValue(value=tenant_id.strip()),
            ),
            qmodels.FieldCondition(
                key="connector_id",
                match=qmodels.MatchValue(value=connector_id),
            ),
            qmodels.FieldCondition(
                key="scope_id",
                match=qmodels.MatchValue(value=self._connector_scope_id),
            ),
        ]
        current_generation = qmodels.FieldCondition(
            key="generation",
            match=qmodels.MatchValue(value=self._generation),
        )
        await self._store.set_payload(
            payload={"is_deleted": True, "reader_ids": []},
            points=qmodels.Filter(
                must=base,
                must_not=[current_generation],
            ),
        )
        await self._store.set_payload(
            payload={"is_deleted": False},
            points=qmodels.Filter(must=[*base, current_generation]),
        )

    async def abort_generation(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
    ) -> None:
        """Keep a failed generation inaccessible and strip its ACL projection."""

        if self._connector_scope_id is None or self._generation is None:
            return
        await self._store.set_payload(
            payload={"is_deleted": True, "reader_ids": []},
            points=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="tenant_id",
                        match=qmodels.MatchValue(value=tenant_id.strip()),
                    ),
                    qmodels.FieldCondition(
                        key="connector_id",
                        match=qmodels.MatchValue(value=connector_id),
                    ),
                    qmodels.FieldCondition(
                        key="scope_id",
                        match=qmodels.MatchValue(value=self._connector_scope_id),
                    ),
                    qmodels.FieldCondition(
                        key="generation",
                        match=qmodels.MatchValue(value=self._generation),
                    ),
                ]
            ),
        )

    async def _soft_delete_points(
        self,
        *,
        tenant_id: str,
        connector_id: str | int,
        item_id: str,
    ) -> None:
        must: list[Any] = [
            qmodels.FieldCondition(
                key="tenant_id",
                match=qmodels.MatchValue(value=tenant_id),
            ),
            qmodels.FieldCondition(
                key="connector_id",
                match=qmodels.MatchValue(value=connector_id),
            ),
            qmodels.FieldCondition(
                key="item_id",
                match=qmodels.MatchValue(value=item_id),
            ),
        ]
        if self._connector_scope_id is not None:
            must.append(
                qmodels.FieldCondition(
                    key="scope_id",
                    match=qmodels.MatchValue(value=self._connector_scope_id),
                )
            )
        if self._generation is not None:
            must.append(
                qmodels.FieldCondition(
                    key="generation",
                    match=qmodels.MatchValue(value=self._generation),
                )
            )
        await self._store.set_payload(
            payload={"is_deleted": True, "reader_ids": []},
            points=qmodels.Filter(must=must),
        )

    async def _persist_canonical(
        self,
        item: DocumentItem,
        chunks: Sequence[Chunk],
        *,
        tenant_id: str,
    ) -> UUID | None:
        if self._session_factory is None:
            return None
        from bothesis.services import DocumentChunkInput, DocumentService

        assert self._connector_scope_id is not None
        assert self._generation is not None
        original = item.original
        metadata = {
            **dict(item.metadata),
            "canonical_item": item.model_dump(mode="json", exclude_none=True),
            "source": item.source.model_dump(mode="json", exclude_none=True),
            "hierarchy": item.hierarchy.model_dump(mode="json", exclude_none=True),
            "document_kind": item.document_kind.value,
        }
        async with self._session_factory.begin() as session:
            documents = DocumentService(session)
            document = await documents.upsert_external_document(
                self._connector_scope_id,
                self._generation,
                item.id,
                title=item.title,
                source_url=item.source.url,
                external_version=item.source.external_version,
                etag=item.source.etag,
                external_updated_at=item.updated_at,
                mime_type=(
                    original.content_type if original else _document_mime_type(item)
                ),
                size_bytes=original.size_bytes if original else None,
                metadata=metadata,
                raw_storage_key=original.key if original else None,
                content_sha256=original.checksum_sha256 if original else None,
                allowed_principal_tokens=item.access.to_reader_ids(),
                denied_principal_tokens=_denied_principal_tokens(item),
            )
            if str(document.tenant_id) != tenant_id:
                raise ValueError("connector sink tenant does not match its database scope")
            if chunks:
                await documents.replace_chunks(
                    document.id,
                    [DocumentChunkInput.from_chunk(chunk) for chunk in chunks],
                )
            else:
                await documents.soft_delete_chunks(document.id)
            return document.id

    async def _mark_indexed(
        self,
        document_id: UUID,
        *,
        allow_empty: bool = False,
    ) -> None:
        assert self._session_factory is not None
        from bothesis.services import DocumentService

        async with self._session_factory.begin() as session:
            await DocumentService(session).mark_indexed(
                document_id,
                allow_empty=allow_empty,
            )

    async def _mark_failed(self, document_id: UUID) -> None:
        assert self._session_factory is not None
        from bothesis.services import DocumentService

        async with self._session_factory.begin() as session:
            await DocumentService(session).mark_index_failed(document_id)

    async def aclose(self) -> None:
        await self._store.aclose()


def _document_mime_type(item: DocumentItem) -> str | None:
    if item.document_kind == DocumentKind.PDF:
        return "application/pdf"
    if item.document_kind == DocumentKind.IMAGE:
        return "image/*"
    if item.document_kind == DocumentKind.WEB_PAGE:
        return "text/html"
    return None


def _denied_principal_tokens(item: DocumentItem) -> list[str]:
    values: list[str] = []
    for rule in item.access.direct.rules:
        if rule.effect != AccessEffect.DENY:
            continue
        principal = rule.principal
        values.append(
            principal.id
            if principal.type == "public"
            or principal.id.startswith(f"{principal.type}:")
            else f"{principal.type}:{principal.id}"
        )
    return values


__all__ = ["QdrantConnectorIndexSink"]
