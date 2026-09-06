"""Provider-neutral navigation targets for grounded citations."""

from urllib.parse import quote, urlsplit, urlunsplit

from bothesis.connector.protocol import CitationInfo, SourceIdentity


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


__all__ = ["CitationResolver"]
