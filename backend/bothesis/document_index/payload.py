"""Projection of connector-produced chunks into the derived Qdrant index."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bothesis.connector.protocol import Chunk, CitationInfo, CitationSpan, DocumentItem
from bothesis.document_index.contextualization import (
    SemanticContextualizer,
    StructuralContextualizer,
)
from bothesis.document_index.models import ContextualChunk


class QdrantPayloadContext(BaseModel):
    """Tenant-owned values that are not part of a connector chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1)
    connector_id: str | int
    scope_id: str | int | None = None
    generation: int | None = Field(default=None, ge=1)
    is_deleted: bool = False
    embedding_model: str | None = None

    @field_validator("tenant_id")
    @classmethod
    def _strip_tenant_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("tenant_id must not be blank")
        return value


class IndexPayload(BaseModel):
    """Bounded retrieval projection of a :class:`ContextualChunk`.

    Raw content parts, complete access policies, storage objects, and arbitrary
    item metadata remain in their canonical stores and are never copied here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 4
    tenant_id: str = Field(min_length=1)
    scope_id: str | int | None = None
    generation: int | None = Field(default=None, ge=1)
    is_deleted: bool = False

    item_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    title: str | None = None
    document_kind: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    chunk_text: str = Field(min_length=1)
    contextual_text: str = Field(min_length=1)
    context_section_path: list[str] = Field(default_factory=list)
    context_summary: str | None = None

    connector_id: str | int
    provider: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    parent_id: str | None = None
    root_id: str | None = None
    ancestor_ids: list[str] = Field(default_factory=list)
    reader_ids: list[str] = Field(default_factory=list)

    source_url: str | None = None
    citation_section: str | None = None
    citation_section_path: list[str] = Field(default_factory=list)
    citation_anchor: str | None = None
    citation_spans: tuple[CitationSpan, ...] = ()
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    embedding_model: str | None = None

    @field_validator("reader_ids")
    @classmethod
    def _normalise_reader_ids(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in value if item.strip()})

    @field_validator("ancestor_ids", "context_section_path")
    @classmethod
    def _normalise_paths(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def _validate_page_range(self) -> "IndexPayload":
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must not precede page_start")
        return self

    @classmethod
    def from_contextual_chunk(
        cls,
        chunk: ContextualChunk,
        context: QdrantPayloadContext,
    ) -> "IndexPayload":
        return cls(
            tenant_id=context.tenant_id,
            scope_id=context.scope_id,
            generation=context.generation,
            is_deleted=context.is_deleted,
            item_id=chunk.item_id,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            title=chunk.title,
            document_kind=chunk.document_kind,
            content_type=chunk.content_type,
            chunk_text=chunk.chunk_text,
            contextual_text=chunk.contextual_text,
            context_section_path=chunk.context.section_path,
            context_summary=chunk.context.summary,
            connector_id=context.connector_id,
            provider=chunk.source.provider.value,
            external_id=chunk.source.external_id,
            parent_id=chunk.hierarchy.parent_id,
            root_id=chunk.hierarchy.root_id,
            ancestor_ids=chunk.hierarchy.ancestor_ids,
            reader_ids=chunk.access.reader_ids,
            source_url=_persisted_source_url(chunk.source.url),
            citation_section=chunk.citation.section,
            citation_section_path=list(chunk.citation.section_path),
            citation_anchor=chunk.citation.anchor,
            citation_spans=chunk.citation.spans,
            page_start=_citation_page_start(chunk.citation),
            page_end=_citation_page_end(chunk.citation),
            embedding_model=context.embedding_model,
        )

    def for_qdrant(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class QdrantChunkRecord(BaseModel):
    """A deterministic Qdrant point paired with its bounded payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point_id: str = Field(min_length=1)
    payload: IndexPayload

    @classmethod
    def from_contextual_chunk(
        cls,
        chunk: ContextualChunk,
        context: QdrantPayloadContext,
    ) -> "QdrantChunkRecord":
        generation_identity = (
            f":{context.scope_id}:{context.generation}"
            if context.generation is not None
            else ""
        )
        point_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{context.tenant_id}:{context.connector_id}{generation_identity}:"
                f"{chunk.item_id}:{chunk.chunk_index}",
            )
        )
        return cls(
            point_id=point_id,
            payload=IndexPayload.from_contextual_chunk(chunk, context),
        )


QdrantChunkPayload = IndexPayload


def build_contextual_chunks(
    chunks: Sequence[Chunk],
    item: DocumentItem,
    *,
    semantic_contextualizer: SemanticContextualizer | None = None,
) -> list[ContextualChunk]:
    """Enrich canonical connector chunks with item-level retrieval metadata.

    Chunk boundaries, evidence text, and citations are connector-owned. This
    function validates that boundary and never reads ``item.content``.
    """

    validated = _validate_chunks(chunks, item)
    structural = StructuralContextualizer()
    summary = _metadata_scalar(item.metadata, "summary")
    return [
        structural.contextualize(
            chunk,
            title=item.title,
            source=item.source,
            hierarchy=item.hierarchy,
            access=item.access,
            document_kind=item.document_kind,
            summary=summary,
            semantic_context=(
                semantic_contextualizer.describe(chunk)
                if semantic_contextualizer is not None
                else None
            ),
        )
        for chunk in validated
    ]


def build_qdrant_records(
    chunks: Sequence[Chunk],
    item: DocumentItem,
    context: QdrantPayloadContext,
    *,
    semantic_contextualizer: SemanticContextualizer | None = None,
) -> list[QdrantChunkRecord]:
    """Contextualize canonical chunks and project deterministic Qdrant points."""

    contextual_chunks = build_contextual_chunks(
        chunks,
        item,
        semantic_contextualizer=semantic_contextualizer,
    )
    return [
        QdrantChunkRecord.from_contextual_chunk(chunk, context)
        for chunk in contextual_chunks
    ]


def _validate_chunks(chunks: Sequence[Chunk], item: DocumentItem) -> tuple[Chunk, ...]:
    if not isinstance(item, DocumentItem):
        raise TypeError("item must be a DocumentItem")
    resolved = tuple(chunks)
    if not resolved:
        raise ValueError(f"Document item {item.id!r} has no connector chunks")

    seen_ids: set[str] = set()
    seen_indexes: set[int] = set()
    for chunk in resolved:
        if not isinstance(chunk, Chunk):
            raise TypeError("chunks must contain only connector Chunk values")
        if chunk.item_id != item.id:
            raise ValueError(
                f"Chunk {chunk.id!r} belongs to item {chunk.item_id!r}, not {item.id!r}"
            )
        if chunk.id in seen_ids:
            raise ValueError(f"Duplicate chunk id {chunk.id!r} for item {item.id!r}")
        if chunk.chunk_index in seen_indexes:
            raise ValueError(
                f"Duplicate chunk index {chunk.chunk_index} for item {item.id!r}"
            )
        seen_ids.add(chunk.id)
        seen_indexes.add(chunk.chunk_index)
    return resolved


def _metadata_scalar(metadata: dict[str, str | list[str]], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, list):
        return value[0].strip() if value and value[0].strip() else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _citation_page_start(citation: CitationInfo) -> int | None:
    pages = [span.page for span in citation.spans if span.page is not None]
    return min(pages) if pages else None


def _citation_page_end(citation: CitationInfo) -> int | None:
    pages = [span.page for span in citation.spans if span.page is not None]
    return max(pages) if pages else None


def _persisted_source_url(value: str | None) -> str | None:
    """Keep provider links, but never index a short-lived storage URL."""

    if not value:
        return None
    query_keys = {key.casefold() for key in parse_qs(urlsplit(value).query)}
    provider_signature = query_keys.intersection(
        {
            "x-amz-algorithm",
            "x-amz-credential",
            "x-amz-expires",
            "x-amz-signature",
            "x-amz-date",
            "x-goog-algorithm",
            "x-goog-credential",
            "x-goog-expires",
            "x-goog-signature",
        }
    )
    generic_signature = {"expires", "signature"}.issubset(query_keys)
    azure_signature = {"se", "sig"}.issubset(query_keys)
    if provider_signature or generic_signature or azure_signature:
        return None
    return value


__all__ = [
    "ContextualChunk",
    "IndexPayload",
    "QdrantChunkPayload",
    "QdrantChunkRecord",
    "QdrantPayloadContext",
    "build_contextual_chunks",
    "build_qdrant_records",
]
