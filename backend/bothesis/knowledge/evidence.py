"""Provider-neutral navigation targets for structured citations."""

from urllib.parse import quote, urlsplit, urlunsplit

from bothesis.document_index.models import CitationInfo, ContextualChunk, SourceIdentity
from .models import Evidence


class CitationResolver:
    """Resolve a citation into an internal viewer path or native source URL."""

    @staticmethod
    def internal_path(item_id: str, chunk_id: str) -> str:
        normalized_item_id = item_id.strip()
        normalized_chunk_id = chunk_id.strip()
        if not normalized_item_id or not normalized_chunk_id:
            raise ValueError("item_id and chunk_id are required")
        return (
            f"/knowledge/items/{quote(normalized_item_id, safe='')}"
            f"?chunk={quote(normalized_chunk_id, safe='')}"
        )

    @staticmethod
    def original_url(source: SourceIdentity, citation: CitationInfo) -> str | None:
        if not source.url:
            return None
        if not citation.anchor:
            return source.url
        parts = urlsplit(source.url)
        anchor = citation.anchor.removeprefix("#")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, anchor))


class EvidenceBuilder:
    """Convert indexed chunks into the bounded evidence contract for agents."""

    def build(self, chunk: ContextualChunk) -> Evidence:
        return Evidence(
            id=chunk.id,
            item_id=chunk.item_id,
            chunk_id=chunk.id,
            collection_item_id=chunk.collection_item_id,
            title=chunk.title or chunk.item_id,
            content=chunk.chunk_text,
            source=chunk.source,
            citation=chunk.citation,
            section_path=tuple(chunk.context.section_path),
            contextual_text=chunk.contextual_text,
            relevance_score=chunk.relevance_score,
            rerank_score=chunk.rerank_score,
        )


__all__ = ["CitationResolver", "EvidenceBuilder"]
