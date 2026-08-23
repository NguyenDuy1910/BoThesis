"""Provider-independent structural and optional semantic contextualization."""

from __future__ import annotations

from collections.abc import Callable

from bothesis.connector.protocol import (
    AccessPolicy,
    Chunk,
    DocumentKind,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
)
from bothesis.document_index.models import ChunkContext, ContextualChunk


class StructuralContextualizer:
    """Add deterministic document structure without changing source evidence."""

    def contextualize(
        self,
        chunk: Chunk,
        *,
        title: str | None,
        source: SourceIdentity,
        hierarchy: Hierarchy,
        access: AccessPolicy | EffectiveAccess,
        document_kind: DocumentKind | str,
        summary: str | None = None,
        semantic_context: str | None = None,
    ) -> ContextualChunk:
        context = ChunkContext(section_path=list(chunk.section_path), summary=summary)
        prefix = []
        if title:
            prefix.append(f"Document: {title}")
        if chunk.section_path:
            prefix.append(f"Section: {' > '.join(chunk.section_path)}")
        if summary:
            prefix.append(f"Context: {summary}")
        if semantic_context and semantic_context.strip():
            prefix.append(f"Description: {semantic_context.strip()}")
        contextual_text = "\n".join(prefix)
        contextual_text = f"{contextual_text}\n\n{chunk.chunk_text}" if contextual_text else chunk.chunk_text
        kind = document_kind.value if isinstance(document_kind, DocumentKind) else document_kind
        effective_access = access.effective if isinstance(access, AccessPolicy) else access
        return ContextualChunk(
            id=chunk.id,
            item_id=chunk.item_id,
            chunk_index=chunk.chunk_index,
            content_type=chunk.content_type,
            chunk_text=chunk.chunk_text,
            contextual_text=contextual_text,
            context=context,
            title=title,
            document_kind=kind,
            source=source,
            hierarchy=hierarchy,
            access=effective_access,
            citation=chunk.citation,
        )


class SemanticContextualizer:
    """Optional generated context provider kept separate from structure."""

    def __init__(self, generator: Callable[[Chunk], str] | None = None) -> None:
        self._generator = generator

    def describe(self, chunk: Chunk) -> str | None:
        if self._generator is None:
            return None
        value = self._generator(chunk)
        return value.strip() or None


__all__ = ["SemanticContextualizer", "StructuralContextualizer"]
