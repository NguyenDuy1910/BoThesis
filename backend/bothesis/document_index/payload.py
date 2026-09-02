"""Flat retrieval projection of connector-produced chunks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bothesis.connector.protocol import (
    Chunk,
    CitationInfo,
    DocumentItem,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index import (
    INDEX_SCHEMA_VERSION,
    ChunkContextGenerator,
    IndexingContext,
    build_contextual_chunks,
)
from bothesis.document_index.models import ChunkContext, ContextualChunk


class IndexedChunk(BaseModel):
    """Bounded retrieval projection of a :class:`ContextualChunk`.

    Raw content parts, complete access policies, storage objects, and arbitrary
    item metadata remain in their canonical stores and are never copied here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = INDEX_SCHEMA_VERSION
    tenant_id: str = Field(min_length=1)
    is_deleted: bool = False

    collection_item_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    title: str | None = None
    document_type: str = Field(min_length=1)
    content_type: str = Field(min_length=1)

    chunk_text: str = Field(min_length=1)
    contextual_text: str = Field(min_length=1)
    section_path: list[str] = Field(default_factory=list)

    parent_item_id: str | None = None
    ancestor_ids: list[str] = Field(default_factory=list)

    connector_key: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    source_url: str | None = None
    citation_anchor: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)

    @field_validator("ancestor_ids", "section_path")
    @classmethod
    def _normalise_paths(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def _validate_page_range(self) -> "IndexedChunk":
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
        context: IndexingContext,
    ) -> "IndexedChunk":
        return cls(
            tenant_id=context.tenant_id,
            collection_item_id=context.collection_item_id,
            item_id=chunk.item_id,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            title=chunk.title,
            document_type=context.document_type,
            content_type=chunk.content_type,
            chunk_text=chunk.chunk_text,
            contextual_text=chunk.contextual_text,
            section_path=_section_path(chunk),
            parent_item_id=context.parent_item_id,
            ancestor_ids=chunk.hierarchy.ancestor_ids,
            connector_key=context.connector_key,
            external_id=chunk.source.external_id,
            source_url=_persisted_source_url(chunk.source.url),
            citation_anchor=chunk.citation.anchor,
            page_start=_citation_page_start(chunk.citation),
            page_end=_citation_page_end(chunk.citation),
        )

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


async def build_index_records(
    chunks: Sequence[Chunk],
    item: DocumentItem,
    context: IndexingContext,
    *,
    semantic_contextualizer: ChunkContextGenerator | None = None,
) -> list[IndexedChunkRecord]:
    """Contextualize canonical chunks and build deterministic index records."""

    from bothesis.document_index import IndexedChunkRecord

    contextual_chunks = await build_contextual_chunks(
        chunks,
        item,
        semantic_contextualizer=semantic_contextualizer,
    )
    return [
        IndexedChunkRecord.from_contextual_chunk(chunk, context)
        for chunk in contextual_chunks
    ]


def contextual_chunk_from_point(point: object) -> ContextualChunk | None:
    """Rebuild one canonical retrieval chunk from an indexed point payload."""

    raw_payload = getattr(point, "payload", None)
    if not isinstance(raw_payload, Mapping):
        return None
    payload = {str(key): value for key, value in raw_payload.items()}
    item_id = _payload_text(payload, "item_id")
    chunk_id = _payload_text(payload, "chunk_id")
    chunk_text = _payload_content(payload, "chunk_text")
    contextual_text = _payload_content(payload, "contextual_text")
    connector_key = _payload_text(payload, "connector_key")
    external_id = _payload_text(payload, "external_id")
    if not all(
        (
            item_id,
            chunk_id,
            chunk_text,
            contextual_text,
            connector_key,
            external_id,
        )
    ):
        return None
    try:
        provider = SourceProvider(connector_key)
    except ValueError:
        return None

    raw_score = getattr(point, "score", None)
    relevance_score = (
        float(raw_score)
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
        else None
    )
    section_path = _payload_strings(payload, "section_path")
    return ContextualChunk(
        id=chunk_id,
        item_id=item_id,
        chunk_index=_payload_int(payload, "chunk_index", default=0) or 0,
        content_type=_payload_text(payload, "content_type") or "text",
        chunk_text=chunk_text,
        contextual_text=contextual_text,
        context=ChunkContext(section_path=section_path),
        title=_payload_text(payload, "title"),
        document_type=_payload_text(payload, "document_type") or "plain_text",
        collection_item_id=_payload_text(payload, "collection_item_id"),
        source=SourceIdentity(
            connector_id=connector_key,
            provider=provider,
            external_id=external_id,
            url=_payload_text(payload, "source_url"),
        ),
        hierarchy=Hierarchy(
            parent_id=_payload_text(payload, "parent_item_id"),
            ancestor_ids=_payload_strings(payload, "ancestor_ids"),
        ),
        access=EffectiveAccess(),
        citation=CitationInfo(
            section=section_path[-1] if section_path else None,
            section_path=tuple(section_path),
            anchor=_payload_text(payload, "citation_anchor"),
            page_start=_payload_int(payload, "page_start"),
            page_end=_payload_int(payload, "page_end"),
        ),
        relevance_score=relevance_score,
    )


def _citation_page_start(citation: CitationInfo) -> int | None:
    if citation.page_start is not None:
        return citation.page_start
    pages = [span.page for span in citation.spans if span.page is not None]
    return min(pages) if pages else None


def _citation_page_end(citation: CitationInfo) -> int | None:
    if citation.page_end is not None:
        return citation.page_end
    pages = [span.page for span in citation.spans if span.page is not None]
    return max(pages) if pages else None


def _section_path(chunk: ContextualChunk) -> list[str]:
    if chunk.context.section_path:
        return list(chunk.context.section_path)
    if chunk.citation.section_path:
        return list(chunk.citation.section_path)
    if chunk.citation.section and chunk.citation.section.strip():
        return [chunk.citation.section]
    return []


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


def _payload_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _payload_content(payload: Mapping[str, object], key: str) -> str | None:
    """Validate evidence text without changing its bytes-as-text projection."""

    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _payload_strings(payload: Mapping[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _payload_int(
    payload: Mapping[str, object],
    key: str,
    *,
    default: int | None = None,
) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return default


__all__ = [
    "ContextualChunk",
    "IndexedChunk",
    "build_contextual_chunks",
    "build_index_records",
    "contextual_chunk_from_point",
]
