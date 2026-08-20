"""Citation-safe final-answer text projection."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

from bothesis.agent.models import Evidence


_CITATION_PREFIX = "[[cite:"
_MAX_MARKER_LENGTH = 256
CitationFragment = tuple[str, str | None]


class CitationRenderer:
    """Remove internal citation markers and identify the grounded evidence used."""

    def __init__(self) -> None:
        self._buffer = ""

    async def render(
        self,
        deltas: tuple[str, ...],
        evidence: Mapping[str, Evidence],
        used_evidence_ids: set[str],
    ) -> AsyncIterator[CitationFragment]:
        for delta in deltas:
            for fragment in self.push(delta, evidence, used_evidence_ids):
                yield fragment
        trailing = self.flush()
        if trailing is not None:
            yield trailing

    def push(
        self,
        delta: str,
        evidence: Mapping[str, Evidence],
        used_evidence_ids: set[str],
    ) -> list[CitationFragment]:
        self._buffer += delta
        fragments, self._buffer = _process_citation_buffer(self._buffer, evidence)
        used_evidence_ids.update(evidence_id for _, evidence_id in fragments if evidence_id)
        return fragments

    def flush(self) -> CitationFragment | None:
        if not self._buffer:
            return None
        text, self._buffer = self._buffer, ""
        return (text, None)


def _process_citation_buffer(
    buffer: str, evidence: Mapping[str, Evidence]
) -> tuple[list[CitationFragment], str]:
    remaining = buffer
    emitted: list[CitationFragment] = []
    while remaining:
        start = remaining.find("[[")
        if start < 0:
            if remaining.endswith("["):
                emitted.append((remaining[:-1], None))
                return emitted, "["
            emitted.append((remaining, None))
            return emitted, ""
        before, candidate = remaining[:start], remaining[start:]
        end = candidate.find("]]", 2)
        if end < 0:
            if (
                _CITATION_PREFIX.startswith(candidate)
                or candidate.startswith(_CITATION_PREFIX)
            ) and len(candidate) <= _MAX_MARKER_LENGTH:
                if before:
                    emitted.append((before, None))
                return emitted, candidate
            emitted.append((remaining, None))
            return emitted, ""
        marker, remaining = candidate[: end + 2], candidate[end + 2 :]
        if before:
            emitted.append((before, None))
        evidence_id = marker[len(_CITATION_PREFIX) : -2]
        if (
            marker.startswith(_CITATION_PREFIX)
            and evidence_id in evidence
            and all(character.isalnum() or character in "_.:-" for character in evidence_id)
        ):
            emitted.append(("", evidence_id))
        else:
            emitted.append((marker, None))
    return emitted, ""


__all__ = ["CitationFragment", "CitationRenderer"]
