"""Build immutable retrieval chunks from canonical connector chunks."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from bothesis.connector.protocol import (
    AccessPolicy,
    Chunk,
    DocumentItem,
    DocumentKind,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
)
from bothesis.document_index import (
    ChunkContext,
    ChunkContextGenerator,
    ContextualChunk,
)

log = logging.getLogger(__name__)

_DOCUMENT_CONTEXT_MAX_CHARACTERS = 12_000
_DOCUMENT_CONTEXT_METADATA_MAX_CHARACTERS = 3_000
_DOCUMENT_CONTEXT_CHUNK_MAX_CHARACTERS = 2_000


class ContextualChunkBuilder:
    """Assemble one retrieval chunk without changing canonical evidence."""

    def contextualize(
        self,
        chunk: Chunk,
        *,
        title: str | None,
        source: SourceIdentity,
        hierarchy: Hierarchy,
        access: AccessPolicy | EffectiveAccess,
        document_type: DocumentKind | str,
        document_summary: str | None = None,
        semantic_context: str | None = None,
    ) -> ContextualChunk:
        context = ChunkContext(
            section_path=list(chunk.section_path),
            summary=document_summary,
        )
        prefix = []
        if title:
            prefix.append(f"Document: {title}")
        if chunk.section_path:
            prefix.append(f"Section: {' > '.join(chunk.section_path)}")
        retrieval_context = (
            semantic_context.strip()
            if semantic_context and semantic_context.strip()
            else document_summary
        )
        if retrieval_context:
            prefix.append(f"Context: {retrieval_context}")
        contextual_text = "\n".join(prefix)
        contextual_text = (
            f"{contextual_text}\n\n{chunk.chunk_text}"
            if contextual_text
            else chunk.chunk_text
        )
        kind = (
            document_type.value
            if isinstance(document_type, DocumentKind)
            else document_type
        )
        effective_access = (
            access.effective if isinstance(access, AccessPolicy) else access
        )
        return ContextualChunk(
            id=chunk.id,
            item_id=chunk.item_id,
            chunk_index=chunk.chunk_index,
            content_type=chunk.content_type,
            chunk_text=chunk.chunk_text,
            contextual_text=contextual_text,
            context=context,
            title=title,
            document_type=kind,
            source=source,
            hierarchy=hierarchy,
            access=effective_access,
            citation=chunk.citation,
        )


async def build_contextual_chunks(
    chunks: Sequence[Chunk],
    item: DocumentItem,
    *,
    semantic_contextualizer: ChunkContextGenerator | None = None,
) -> list[ContextualChunk]:
    """Build retrieval text without modifying canonical evidence or citations."""

    validated = _validate_chunks(chunks, item)
    chunk_builder = ContextualChunkBuilder()
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
            except Exception as exc:  # noqa: BLE001 - enrichment is best effort
                log.warning(
                    "semantic context generation failed for chunk %s; "
                    "using structural context: %s",
                    chunk.id,
                    type(exc).__name__,
                )
        contextual.append(
            chunk_builder.contextualize(
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
            " > ".join(chunk.section_path) for chunk in chunks if chunk.section_path
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


__all__ = [
    "ContextualChunkBuilder",
    "build_contextual_chunks",
]
