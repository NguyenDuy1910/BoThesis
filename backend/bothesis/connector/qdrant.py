"""Contextual chunking and the flat Qdrant retrieval projection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bothesis.knowledge.protocol import (
    AnyContentPart,
    AnyItem,
    BoundingBox,
    Chunk,
    ChunkContext,
    CitationInfo,
    CitationSpan,
    ContextualChunk,
    DocumentItem,
    ImagePart,
    LinkPart,
    StructuredPart,
    TablePart,
    TextPart,
)


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    max_characters: int = 4_000
    overlap_characters: int = 400

    def __post_init__(self) -> None:
        if self.max_characters < 100:
            raise ValueError("max_characters must be at least 100")
        if not 0 <= self.overlap_characters < self.max_characters:
            raise ValueError(
                "overlap_characters must be non-negative and smaller than max_characters"
            )


class QdrantPayloadContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1)
    connector_id: str | int
    scope_id: str | int | None = None
    embedding_model: str | None = None

    @field_validator("tenant_id")
    @classmethod
    def _strip_tenant_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("tenant_id must not be blank")
        return value


class QdrantChunkPayload(BaseModel):
    """Flat retrieval projection of a ContextualChunk.

    AccessPolicy, StorageObject, and arbitrary Item metadata remain in the
    canonical Item store and are intentionally not copied into Qdrant.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 3
    tenant_id: str = Field(min_length=1)
    scope_id: str | int | None = None
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

    # Source identity is kept separate from the evidence locator below.
    source_url: str | None = None
    citation_section: str | None = None
    citation_section_path: list[str] = Field(default_factory=list)
    citation_anchor: str | None = None
    citation_spans: tuple[CitationSpan, ...] = ()
    # These are intentionally derived, bounded fields for filtering and
    # diagnostics.  ``citation_spans`` remains the canonical locator.
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    embedding_model: str | None = None

    @field_validator("reader_ids")
    @classmethod
    def _normalise_reader_ids(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in value if item.strip()})

    @field_validator("ancestor_ids", "context_section_path", "citation_section_path")
    @classmethod
    def _normalise_strings(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def _validate_page_range(self) -> "QdrantChunkPayload":
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
    ) -> "QdrantChunkPayload":
        return cls(
            tenant_id=context.tenant_id,
            scope_id=context.scope_id,
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
    """A deterministic Qdrant point paired with its flat payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point_id: str = Field(min_length=1)
    payload: QdrantChunkPayload

    @classmethod
    def from_contextual_chunk(
        cls,
        chunk: ContextualChunk,
        context: QdrantPayloadContext,
    ) -> "QdrantChunkRecord":
        point_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{context.tenant_id}:{context.connector_id}:{chunk.item_id}:{chunk.chunk_index}",
            )
        )
        return cls(
            point_id=point_id,
            payload=QdrantChunkPayload.from_contextual_chunk(chunk, context),
        )


def build_contextual_chunks(
    item: AnyItem,
    *,
    chunking: ChunkingConfig | None = None,
) -> list[ContextualChunk]:
    if not isinstance(item, DocumentItem):
        raise ValueError(f"Only DocumentItem values can be indexed: {item.id!r}")
    resolved = chunking or ChunkingConfig()
    default_section_path = _metadata_path(item.metadata)
    summary = _metadata_scalar(item.metadata, "summary")
    elements = _normalised_elements(item, default_section_path)
    chunks: list[ContextualChunk] = []
    for batch in _element_batches(elements):
        document_text = "\n\n".join(element.text for element in batch)
        for fragment, start_offset, end_offset in split_text_with_offsets(document_text, resolved):
            spans = _citation_spans_for_range(batch, start_offset, end_offset)
            if not spans:
                continue
            index = len(chunks)
            first = spans[0]
            first_element = next(
                element for element in batch if element.element_id == first.element_id
            )
            section_path = list(first_element.section_path)
            section = first_element.section
            anchor = first_element.anchor
            citation = CitationInfo(
                section=section,
                section_path=tuple(section_path),
                anchor=anchor,
                spans=tuple(spans),
            )
            context = ChunkContext(section_path=section_path, summary=summary)
            content_types = {element.content_type for element in batch if any(
                span.element_id == element.element_id for span in spans
            )}
            content_type = next(iter(content_types)) if len(content_types) == 1 else "mixed"
            chunk = Chunk(
                id=f"{item.id}:{index}",
                item_id=item.id,
                chunk_index=index,
                chunk_text=fragment,
                content_type=content_type,
                section_path=section_path,
                citation=citation,
            )
            chunks.append(
                ContextualChunk(
                    id=chunk.id,
                    item_id=item.id,
                    chunk_index=index,
                    content_type=content_type,
                    chunk_text=fragment,
                    contextual_text=make_contextual_text(
                        title=item.title,
                        context=context,
                        chunk_text=fragment,
                    ),
                    context=context,
                    title=item.title,
                    document_kind=item.document_kind.value,
                    source=item.source,
                    hierarchy=item.hierarchy,
                    access=item.access.effective,
                    citation=chunk.citation,
                )
            )
    if not chunks:
        raise ValueError(f"Document item {item.id!r} has no indexable content")
    return chunks


def build_qdrant_records(
    item: AnyItem,
    context: QdrantPayloadContext,
    *,
    chunking: ChunkingConfig | None = None,
) -> list[QdrantChunkRecord]:
    return [
        QdrantChunkRecord.from_contextual_chunk(chunk, context)
        for chunk in build_contextual_chunks(item, chunking=chunking)
    ]


def make_contextual_text(
    *,
    title: str | None,
    context: ChunkContext,
    chunk_text: str,
) -> str:
    lines: list[str] = []
    if title:
        lines.append(f"Document: {title}")
    if context.section_path:
        lines.append(f"Section: {' > '.join(context.section_path)}")
    if context.summary:
        lines.append(f"Context: {context.summary}")
    prefix = "\n".join(lines)
    return f"{prefix}\n\n{chunk_text}" if prefix else chunk_text


def _content_text(part: AnyContentPart) -> tuple[str, str]:
    if isinstance(part, TextPart):
        return part.text, "text"
    if isinstance(part, ImagePart):
        values = [part.description, part.alt_text, part.ocr_text]
        return "\n".join(value for value in values if value), "image"
    if isinstance(part, TablePart):
        rows = [" | ".join(cell.strip() for cell in row) for row in part.rows]
        table_text = "\n".join(row for row in rows if row)
        if part.caption:
            table_text = f"{part.caption}\n{table_text}" if table_text else part.caption
        return table_text, "table"
    if isinstance(part, StructuredPart):
        return json.dumps(part.data, ensure_ascii=False, sort_keys=True), "structured"
    if isinstance(part, LinkPart):
        return f"{part.title}: {part.url}" if part.title else part.url, "link"
    return f"```{getattr(part, 'language', '')}\n{part.code}\n```", "code"


@dataclass(frozen=True, slots=True)
class _NormalizedElement:
    element_id: str
    text: str
    content_type: str
    page: int | None
    section: str | None
    section_path: tuple[str, ...]
    anchor: str | None
    bounding_box: BoundingBox | None
    document_start: int


def _normalised_elements(
    item: DocumentItem,
    default_section_path: list[str],
) -> list[_NormalizedElement]:
    elements: list[_NormalizedElement] = []
    document_start = 0
    fallback_page = _metadata_int(item.metadata, "page_number")
    fallback_anchor = _metadata_scalar(item.metadata, "anchor")
    for part_index, part in enumerate(item.content):
        raw_text, content_type = _content_text(part)
        text = _normalise_document_text(raw_text)
        if not text:
            continue
        section_path = tuple(part.section_path) or tuple(default_section_path)
        elements.append(
            _NormalizedElement(
                element_id=part.element_id or f"element_{part_index + 1:03d}",
                text=text,
                content_type=content_type,
                page=part.page or fallback_page,
                section=part.section or (section_path[-1] if section_path else None),
                section_path=section_path,
                anchor=part.anchor or fallback_anchor,
                bounding_box=part.bounding_box,
                document_start=document_start,
            )
        )
        document_start += len(text) + 2
    return elements


def _element_batches(
    elements: list[_NormalizedElement],
) -> list[list[_NormalizedElement]]:
    """Pack textual elements semantically while keeping visual evidence typed."""

    batches: list[list[_NormalizedElement]] = []
    text_batch: list[_NormalizedElement] = []
    for element in elements:
        if element.content_type == "text":
            text_batch.append(element)
            continue
        if text_batch:
            batches.append(text_batch)
            text_batch = []
        batches.append([element])
    if text_batch:
        batches.append(text_batch)
    return batches


def citation_spans_for_range(
    elements: list[tuple[str, str, int | None, BoundingBox | None]],
    start_offset: int,
    end_offset: int,
) -> tuple[CitationSpan, ...]:
    """Map a normalized document range to element-local citation spans.

    ``elements`` contains ``(element_id, text, page, bounding_box)`` and uses
    the same two-newline separator as the semantic document stream.
    """

    output: list[CitationSpan] = []
    cursor = 0
    for element_id, text, page, bounding_box in elements:
        element_start = cursor
        element_end = cursor + len(text)
        overlap_start = max(start_offset, element_start)
        overlap_end = min(end_offset, element_end)
        if overlap_start < overlap_end:
            output.append(
                CitationSpan(
                    page=page,
                    element_id=element_id,
                    start_offset=overlap_start - element_start,
                    end_offset=overlap_end - element_start,
                    bounding_box=bounding_box,
                )
            )
        cursor = element_end + 2
    return tuple(output)


def _citation_spans_for_range(
    elements: list[_NormalizedElement],
    start_offset: int,
    end_offset: int,
) -> tuple[CitationSpan, ...]:
    return citation_spans_for_range(
        [
            (element.element_id, element.text, element.page, element.bounding_box)
            for element in elements
        ],
        start_offset,
        end_offset,
    )


def _normalise_document_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return re.sub(r"[ \t]+", " ", value).strip()


def split_text(value: str, config: ChunkingConfig | None = None) -> list[str]:
    return [fragment for fragment, _, _ in split_text_with_offsets(value, config)]


def split_text_with_offsets(
    value: str,
    config: ChunkingConfig | None = None,
) -> list[tuple[str, int, int]]:
    resolved = config or ChunkingConfig()
    value = _normalise_document_text(value)
    if not value:
        return []
    if len(value) <= resolved.max_characters:
        return [(value, 0, len(value))]
    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(value):
        proposed_end = min(start + resolved.max_characters, len(value))
        end = proposed_end
        if proposed_end < len(value):
            minimum_break = start + resolved.max_characters // 2
            candidate_end = max(
                value.rfind("\n\n", minimum_break, proposed_end),
                value.rfind("\n", minimum_break, proposed_end),
                value.rfind(" ", minimum_break, proposed_end),
                -1,
            )
            end = candidate_end if candidate_end > start else proposed_end
        raw_fragment = value[start:end]
        left_trimmed = len(raw_fragment) - len(raw_fragment.lstrip())
        right_trimmed = len(raw_fragment.rstrip())
        fragment_start = start + left_trimmed
        fragment_end = start + right_trimmed
        fragment = value[fragment_start:fragment_end]
        if fragment:
            chunks.append((fragment, fragment_start, fragment_end))
        if end >= len(value):
            break
        next_start = max(end - resolved.overlap_characters, start + 1)
        while next_start < end and not value[next_start - 1].isspace():
            next_start += 1
        start = next_start if next_start < end else end
    return chunks


def _metadata_scalar(metadata: dict[str, str | list[str]], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, list):
        return value[0].strip() if value and value[0].strip() else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _metadata_path(metadata: dict[str, str | list[str]]) -> list[str]:
    value = metadata.get("heading_path") or metadata.get("section_path")
    if isinstance(value, list):
        return [item.strip() for item in value if item.strip()]
    return [value.strip()] if isinstance(value, str) and value.strip() else []


def _metadata_int(metadata: dict[str, str | list[str]], key: str) -> int | None:
    value = _metadata_scalar(metadata, key)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _citation_page_start(citation: CitationInfo) -> int | None:
    pages = [span.page for span in citation.spans if span.page is not None]
    return min(pages) if pages else None


def _citation_page_end(citation: CitationInfo) -> int | None:
    pages = [span.page for span in citation.spans if span.page is not None]
    return max(pages) if pages else None


def _persisted_source_url(value: str | None) -> str | None:
    """Keep provider links, but never put a short-lived storage URL in Qdrant."""

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
    if provider_signature or generic_signature:
        return None
    return value


__all__ = [
    "ChunkingConfig",
    "ContextualChunk",
    "QdrantChunkPayload",
    "QdrantChunkRecord",
    "QdrantPayloadContext",
    "build_contextual_chunks",
    "build_qdrant_records",
    "citation_spans_for_range",
    "make_contextual_text",
    "split_text",
    "split_text_with_offsets",
]
