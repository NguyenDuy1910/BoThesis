"""Projection of connector-produced chunks into the derived Qdrant index."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bothesis.connector.protocol import Chunk, CitationInfo, CitationSpan, DocumentItem
from bothesis.document_index import INDEX_SCHEMA_VERSION
from bothesis.document_index.contextualization import StructuralContextualizer
from bothesis.document_index.models import ContextualChunk
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer

log = logging.getLogger(__name__)

_DOCUMENT_CONTEXT_MAX_CHARACTERS = 12_000
_DOCUMENT_CONTEXT_METADATA_MAX_CHARACTERS = 3_000
_DOCUMENT_CONTEXT_CHUNK_MAX_CHARACTERS = 2_000


class QdrantPayloadContext(BaseModel):
    """Tenant-owned values that are not part of a connector chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1)
    integration_connection_id: str | None = None
    ingestion_source_id: str | None = None
    collection_item_id: str = Field(min_length=1)
    parent_item_id: str | None = None
    document_type: str = Field(min_length=1)
    connector_key: str = Field(min_length=1)
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

    schema_version: int = INDEX_SCHEMA_VERSION
    tenant_id: str = Field(min_length=1)
    integration_connection_id: str | None = None
    ingestion_source_id: str | None = None
    is_deleted: bool = False

    item_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    title: str | None = None
    collection_item_id: str = Field(min_length=1)
    parent_item_id: str | None = None
    document_type: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    chunk_text: str = Field(min_length=1)
    contextual_text: str = Field(min_length=1)
    context_section_path: list[str] = Field(default_factory=list)
    context_summary: str | None = None

    connector_key: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    root_id: str | None = None
    ancestor_ids: list[str] = Field(default_factory=list)

    source_url: str | None = None
    citation_section: str | None = None
    citation_section_path: list[str] = Field(default_factory=list)
    citation_anchor: str | None = None
    citation_spans: tuple[CitationSpan, ...] = ()
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    embedding_model: str | None = None

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
            integration_connection_id=context.integration_connection_id,
            ingestion_source_id=context.ingestion_source_id,
            is_deleted=context.is_deleted,
            item_id=chunk.item_id,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            title=chunk.title,
            collection_item_id=context.collection_item_id,
            parent_item_id=context.parent_item_id,
            document_type=context.document_type,
            content_type=chunk.content_type,
            chunk_text=chunk.chunk_text,
            contextual_text=chunk.contextual_text,
            context_section_path=chunk.context.section_path,
            context_summary=chunk.context.summary,
            connector_key=context.connector_key,
            external_id=chunk.source.external_id,
            root_id=chunk.hierarchy.root_id,
            ancestor_ids=chunk.hierarchy.ancestor_ids,
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
        point_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{context.tenant_id}:{chunk.item_id}:{chunk.chunk_index}",
            )
        )
        return cls(
            point_id=point_id,
            payload=IndexPayload.from_contextual_chunk(chunk, context),
        )


QdrantChunkPayload = IndexPayload


async def build_contextual_chunks(
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
    contextual: list[ContextualChunk] = []
    for chunk in validated:
        semantic_context: str | None = None
        if semantic_contextualizer is not None:
            try:
                semantic_context = await semantic_contextualizer.describe(
                    chunk,
                    document_context=_document_context(
                        item,
                        validated,
                        target=chunk,
                        summary=summary,
                    ),
                    title=item.title,
                    section_path=chunk.section_path,
                )
            except Exception as exc:
                log.warning(
                    "semantic contextualization failed for chunk %s; using summary: %s",
                    chunk.id,
                    type(exc).__name__,
                )
        contextual.append(
            structural.contextualize(
                chunk,
                title=item.title,
                source=item.source,
                hierarchy=item.hierarchy,
                access=item.access,
                document_type=item.document_kind,
                document_summary=summary,
                semantic_context=semantic_context,
            )
        )
    return contextual


async def build_qdrant_records(
    chunks: Sequence[Chunk],
    item: DocumentItem,
    context: QdrantPayloadContext,
    *,
    semantic_contextualizer: SemanticContextualizer | None = None,
) -> list[QdrantChunkRecord]:
    """Contextualize canonical chunks and project deterministic Qdrant points."""

    contextual_chunks = await build_contextual_chunks(
        chunks,
        item,
        semantic_contextualizer=semantic_contextualizer,
    )
    return [
        QdrantChunkRecord.from_contextual_chunk(chunk, context)
        for chunk in contextual_chunks
    ]


def _document_context(
    item: DocumentItem,
    chunks: Sequence[Chunk],
    *,
    target: Chunk,
    summary: str | None,
) -> str:
    """Build bounded metadata and target-relevant canonical chunk context."""

    metadata = [f"Document: {item.title or item.id}"]
    kind = (
        item.document_kind.value
        if hasattr(item.document_kind, "value")
        else str(item.document_kind)
    )
    metadata.append(f"Document kind: {kind}")
    if summary:
        metadata.append(f"Summary: {summary}")
    sections = list(
        dict.fromkeys(
            " > ".join(chunk.section_path)
            for chunk in chunks
            if chunk.section_path
        )
    )
    if sections:
        metadata.append(f"Sections: {'; '.join(sections)}")
    metadata_text = _prompt_text_prefix(
        "\n".join(metadata),
        _DOCUMENT_CONTEXT_METADATA_MAX_CHARACTERS,
    )
    lines = [metadata_text, "Relevant canonical chunk excerpts (target excluded):"]
    remaining = _DOCUMENT_CONTEXT_MAX_CHARACTERS - sum(
        _prompt_text_length(line) + 1 for line in lines
    )
    candidates = sorted(
        (chunk for chunk in chunks if chunk.id != target.id),
        key=lambda chunk: (
            chunk.section_path != target.section_path,
            abs(chunk.chunk_index - target.chunk_index),
            chunk.chunk_index,
        ),
    )
    for chunk in candidates:
        if remaining <= 0:
            break
        section = " > ".join(chunk.section_path)
        label = f"[{chunk.chunk_index}{f' | {section}' if section else ''}] "
        excerpt = label + chunk.chunk_text[:_DOCUMENT_CONTEXT_CHUNK_MAX_CHARACTERS]
        bounded = _prompt_text_prefix(excerpt, remaining)
        lines.append(bounded)
        remaining -= _prompt_text_length(bounded) + 1
    return "\n".join(lines)


def _prompt_text_length(value: str) -> int:
    """Measure text after the prompt renderer escapes XML tag delimiters."""

    return sum(5 if char == "&" else 4 if char in "<>" else 1 for char in value)


def _prompt_text_prefix(value: str, budget: int) -> str:
    if budget <= 0:
        return ""
    consumed = 0
    end = 0
    for end, char in enumerate(value, start=1):
        consumed += 5 if char == "&" else 4 if char in "<>" else 1
        if consumed > budget:
            return value[: end - 1]
    return value


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
