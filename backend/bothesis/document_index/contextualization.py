"""Provider-independent structural contextualization."""

from __future__ import annotations

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
        contextual_text = f"{contextual_text}\n\n{chunk.chunk_text}" if contextual_text else chunk.chunk_text
        kind = document_type.value if isinstance(document_type, DocumentKind) else document_type
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
            document_type=kind,
            source=source,
            hierarchy=hierarchy,
            access=effective_access,
            citation=chunk.citation,
        )
__all__ = ["StructuralContextualizer"]
