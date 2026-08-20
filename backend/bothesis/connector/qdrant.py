"""Typed hand-off contract from connector processing to Qdrant indexing.

This module deliberately does not import ``qdrant_client``. It defines the
validated payload and deterministic point identifier that an indexing worker
can embed and pass to the repository's Qdrant boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import DocumentSource, SourceDocument


class ChunkKind(str, Enum):
    TEXT = "text"
    ATTACHMENT = "attachment"
    FILE = "file"


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


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(ge=0)
    section_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    source_link: str | None = None
    section_title: str | None = None

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("chunk content must not be blank")
        return stripped


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
    """Strict JSON payload consumed by retrieval and permission filters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    tenant_id: str = Field(min_length=1)
    connector_id: str | int
    scope_id: str | int | None = None

    document_id: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    external_version: str | None = None
    etag: str | None = None
    chunk_id: int = Field(ge=0)
    chunk_index: int = Field(ge=0)
    section_id: str = Field(min_length=1)
    section_index: int = Field(ge=0)

    title: str = Field(min_length=1)
    section_title: str | None = None
    semantic_identifier: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_link: str | None = None
    chunk_kind: ChunkKind = ChunkKind.TEXT
    content_type: str = "text/plain"
    language: str | None = None

    access_control_list: list[str] = Field(default_factory=list)
    owner_user_id: str | None = None
    is_public: bool = False
    is_deleted: bool = False

    metadata: dict[str, str | list[str]] = Field(default_factory=dict)
    doc_type: str | None = None
    domains: list[str] = Field(default_factory=list)
    project_key: str | None = None
    space_key: str | None = None
    ticket_status: str | None = None
    ticket_type: str | None = None
    parent_content_id: str | None = None
    attachment_id: str | None = None
    comment_id: str | None = None
    sheet_name: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    heading_path: list[str] = Field(default_factory=list)

    parent_hierarchy_raw_node_id: str | None = None
    hierarchy_node_id: int | None = None
    ancestor_hierarchy_node_ids: list[int] = Field(default_factory=list)
    doc_created_at: datetime | None = None
    doc_updated_at: datetime | None = None
    primary_owners: list[str] = Field(default_factory=list)
    secondary_owners: list[str] = Field(default_factory=list)

    raw_storage_bucket: str | None = None
    raw_storage_key: str | None = None
    raw_storage_region: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    embedding_model: str | None = None
    source_fingerprint: str | None = None

    @field_validator("access_control_list")
    @classmethod
    def _normalise_reader_ids(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in value if item.strip()})

    def for_qdrant(self) -> dict[str, Any]:
        """Return JSON-native data with optional fields omitted."""

        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_document(
        cls,
        document: SourceDocument,
        chunk: DocumentChunk,
        context: QdrantPayloadContext,
    ) -> QdrantChunkPayload:
        metadata = dict(document.metadata)
        source = document.source.value
        return cls(
            tenant_id=context.tenant_id,
            connector_id=context.connector_id,
            scope_id=context.scope_id,
            document_id=document.external_id,
            external_id=document.external_id,
            external_version=document.external_version,
            etag=document.etag,
            chunk_id=chunk.position,
            chunk_index=chunk.position,
            section_id=f"{document.external_id}::{chunk.position}",
            section_index=chunk.section_index,
            title=(document.title or document.semantic_identifier).strip(),
            section_title=chunk.section_title,
            semantic_identifier=document.semantic_identifier,
            content=chunk.content,
            source=source,
            source_type=source,
            source_system=source,
            source_link=chunk.source_link or document.source_link,
            chunk_kind=_chunk_kind(document),
            content_type=document.mime_type or "text/plain",
            language=_metadata_scalar(metadata, "language"),
            access_control_list=document.acl.to_reader_ids(),
            is_public=document.acl.is_public,
            metadata=metadata,
            doc_type=_metadata_scalar(metadata, "doc_type"),
            domains=_metadata_list(metadata, "domains"),
            project_key=_metadata_scalar(metadata, "project_key"),
            space_key=_metadata_scalar(metadata, "space_key"),
            ticket_status=(
                _metadata_scalar(metadata, "ticket_status")
                or _metadata_scalar(metadata, "status")
            ),
            ticket_type=(
                _metadata_scalar(metadata, "ticket_type")
                or _metadata_scalar(metadata, "issue_type")
            ),
            parent_content_id=_metadata_scalar(metadata, "parent_content_id"),
            attachment_id=_metadata_scalar(metadata, "attachment_id"),
            comment_id=_metadata_scalar(metadata, "comment_id"),
            sheet_name=_metadata_scalar(metadata, "sheet_name"),
            parent_hierarchy_raw_node_id=document.parent_hierarchy_raw_node_id,
            doc_created_at=document.doc_created_at,
            doc_updated_at=document.doc_updated_at,
            primary_owners=_owner_ids(document.primary_owners),
            secondary_owners=_owner_ids(document.secondary_owners),
            raw_storage_bucket=document.raw_storage_bucket,
            raw_storage_key=document.raw_storage_key,
            raw_storage_region=document.raw_storage_region,
            mime_type=document.mime_type,
            file_name=document.file_name,
            size_bytes=document.size_bytes,
            embedding_model=context.embedding_model,
        )


class QdrantChunkRecord(BaseModel):
    """A stable Qdrant point identifier paired with its validated payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point_id: str = Field(min_length=1)
    payload: QdrantChunkPayload

    @classmethod
    def from_payload(cls, payload: QdrantChunkPayload) -> QdrantChunkRecord:
        identity = (
            f"{payload.tenant_id}:{payload.connector_id}:"
            f"{payload.document_id}:{payload.chunk_id}"
        )
        return cls(point_id=str(uuid5(NAMESPACE_URL, identity)), payload=payload)


def chunk_document(
    document: SourceDocument,
    config: ChunkingConfig | None = None,
) -> list[DocumentChunk]:
    """Split section text deterministically without crossing section lineage."""

    resolved = config or ChunkingConfig()
    chunks: list[DocumentChunk] = []
    for section_index, section in enumerate(document.sections):
        if not section.text or not section.text.strip():
            continue
        for fragment in split_text(section.text, resolved):
            chunks.append(
                DocumentChunk(
                    position=len(chunks),
                    section_index=section_index,
                    content=fragment,
                    source_link=section.link,
                )
            )
    if not chunks:
        raise ValueError(f"Document {document.external_id!r} has no indexable text")
    return chunks


def build_qdrant_records(
    document: SourceDocument,
    context: QdrantPayloadContext,
    *,
    chunking: ChunkingConfig | None = None,
) -> list[QdrantChunkRecord]:
    return [
        QdrantChunkRecord.from_payload(
            QdrantChunkPayload.from_document(document, chunk, context)
        )
        for chunk in chunk_document(document, chunking)
    ]


def _normalise_document_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return re.sub(r"[ \t]+", " ", value).strip()


def split_text(
    value: str,
    config: ChunkingConfig | None = None,
) -> list[str]:
    """Split normalized text with the connector-wide deterministic policy."""

    resolved = config or ChunkingConfig()
    value = _normalise_document_text(value)
    if not value:
        return []
    if len(value) <= resolved.max_characters:
        return [value]
    chunks: list[str] = []
    start = 0
    length = len(value)
    while start < length:
        proposed_end = min(start + resolved.max_characters, length)
        end = proposed_end
        if proposed_end < length:
            minimum_break = start + resolved.max_characters // 2
            candidates = (
                value.rfind("\n\n", minimum_break, proposed_end),
                value.rfind("\n", minimum_break, proposed_end),
                value.rfind(" ", minimum_break, proposed_end),
            )
            boundary = max(candidates)
            if boundary > start:
                end = boundary
        fragment = value[start:end].strip()
        if fragment:
            chunks.append(fragment)
        if end >= length:
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


def _metadata_list(metadata: dict[str, str | list[str]], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, list):
        return [item.strip() for item in value if item.strip()]
    return [value.strip()] if isinstance(value, str) and value.strip() else []


def _owner_ids(owners: list[Any] | None) -> list[str]:
    if not owners:
        return []
    return sorted(
        {
            str(owner.email or owner.username or owner.name).strip().lower()
            for owner in owners
            if str(owner.email or owner.username or owner.name).strip()
        }
    )


def _chunk_kind(document: SourceDocument) -> ChunkKind:
    if "attachment_id" in document.metadata:
        return ChunkKind.ATTACHMENT
    if document.source == DocumentSource.FILE or document.file_name:
        return ChunkKind.FILE
    return ChunkKind.TEXT


__all__ = [
    "ChunkKind",
    "ChunkingConfig",
    "DocumentChunk",
    "QdrantChunkPayload",
    "QdrantChunkRecord",
    "QdrantPayloadContext",
    "build_qdrant_records",
    "chunk_document",
    "split_text",
]
