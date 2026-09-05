"""Bounded context construction for ranked enterprise evidence."""

from __future__ import annotations

from collections.abc import Sequence

from bothesis.knowledge import Evidence, EvidenceContext


class EvidenceContextBuilder:
    """Preserve ranking and identities while bounding model-facing evidence."""

    def __init__(
        self,
        *,
        max_characters: int = 8_000,
        max_evidence_characters: int = 1_600,
        include_contextual_text: bool = False,
    ) -> None:
        if max_characters < 1 or max_evidence_characters < 1:
            raise ValueError("context limits must be greater than zero")
        self._max_characters = max_characters
        self._max_evidence_characters = max_evidence_characters
        self._include_contextual_text = include_contextual_text

    def build(self, evidence: Sequence[Evidence]) -> EvidenceContext:
        introduction = (
            "Retrieved access-permitted enterprise evidence.\n"
            "Cite with [[cite:ref_id]] immediately after each claim it "
            "supports, never collected at the end. Repeat it on every claim, "
            "and place several together when a claim rests on several "
            "sources.\n"
            "Only the references below exist. Never invent one, and never "
            "write a page, URL, chunk ID, or coordinate.\n\n"
        )
        blocks: list[str] = []
        included: list[Evidence] = []
        seen_chunks: set[tuple[str, str]] = set()
        remaining = self._max_characters - len(introduction)
        if remaining <= 0:
            return EvidenceContext(text="", evidence=())
        for item in evidence:
            identity = (item.item_id, item.chunk_id)
            if identity in seen_chunks:
                continue
            header = self._header(item)
            available = min(
                self._max_evidence_characters,
                remaining - len(header) - 2,
            )
            if available <= 0:
                break
            body = self._body(item, available)
            if not body:
                continue
            block = f"{header}\nEvidence:\n{body}"
            if len(block) > remaining:
                break
            blocks.append(block)
            included.append(item)
            seen_chunks.add(identity)
            remaining -= len(block) + 2

        if not blocks:
            return EvidenceContext(text="", evidence=())
        return EvidenceContext(
            text=introduction + "\n\n".join(blocks),
            evidence=tuple(included),
        )

    def _header(self, item: Evidence) -> str:
        # Internal Item and chunk identifiers stay out of the model context.
        # The source reference is the only identity the model can cite, and the
        # backend resolves it back to canonical citation metadata.
        lines = [
            f"--- Document: {item.title or 'Untitled source'} ---",
            f"Source reference: {item.id}",
        ]
        if item.section_path:
            lines.append(f"Section: {' > '.join(item.section_path)}")
        pages = _page_label(item)
        if pages is not None:
            lines.append(f"Page: {pages}")
        if item.source is not None:
            lines.append(f"Origin: {item.source.provider.value}")
            if item.source.url:
                lines.append(f"Source URL: {item.source.url}")
        return "\n".join(lines)

    def _body(self, item: Evidence, limit: int) -> str:
        canonical = self._clip(item.content, limit)
        if not self._include_contextual_text or not item.contextual_text:
            return canonical
        contextual = item.contextual_text.strip()
        if contextual == item.content.strip():
            return canonical
        prefix = "Retrieval context (not canonical evidence):\n"
        separator = "\nCanonical evidence:\n"
        canonical_budget = max(1, min(len(item.content), limit * 3 // 4))
        context_budget = limit - len(prefix) - len(separator) - canonical_budget
        if context_budget < 80:
            return canonical
        return (
            f"{prefix}{self._clip(contextual, context_budget)}"
            f"{separator}{self._clip(item.content, canonical_budget)}"
        )

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return f"{text[: max(1, limit - 1)].rstrip()}…"


def _page_label(item: Evidence) -> str | None:
    start = item.citation.page_start
    end = item.citation.page_end
    if start is None:
        return str(end) if end is not None else None
    if end is None or end == start:
        return str(start)
    return f"{start}-{end}"


__all__ = ["EvidenceContextBuilder"]
