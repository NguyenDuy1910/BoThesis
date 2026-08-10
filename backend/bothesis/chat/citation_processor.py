"""Incrementally convert grounded citation markers into chat events."""

from __future__ import annotations

from collections.abc import Mapping

from bothesis.agent.models import CitationEvent, Evidence, MessageDelta

_CITATION_PREFIX = "[[cite:"
_MAX_CITATION_MARKER_LENGTH = 256


def process_citation_buffer(
    buffer: str,
    evidence: Mapping[str, Evidence],
) -> tuple[list[MessageDelta | CitationEvent], str]:
    """Return visible events and any incomplete marker to carry forward."""

    remaining = buffer
    emitted: list[MessageDelta | CitationEvent] = []
    known_ids = set(evidence)
    while remaining:
        text, evidence_ids, next_remaining = _parse_citations(remaining, known_ids)
        if text:
            emitted.append(MessageDelta(text=text))
        for evidence_id in evidence_ids:
            item = evidence[evidence_id]
            emitted.append(
                CitationEvent(
                    evidence_id=evidence_id,
                    title=item.title,
                    page=item.page,
                    uri=item.uri,
                )
            )
        if next_remaining == remaining:
            return emitted, next_remaining
        remaining = next_remaining
    return emitted, ""


def _parse_citations(
    buffer: str,
    known_evidence_ids: set[str],
) -> tuple[str, list[str], str]:
    marker_start = buffer.find("[[")
    if marker_start < 0:
        if buffer.endswith("["):
            return buffer[:-1], [], "["
        return buffer, [], ""
    before = buffer[:marker_start]
    candidate = buffer[marker_start:]
    marker_end = candidate.find("]]")
    if marker_end < 0:
        if (
            _CITATION_PREFIX.startswith(candidate)
            or candidate.startswith(_CITATION_PREFIX)
        ) and len(candidate) <= _MAX_CITATION_MARKER_LENGTH:
            return before, [], candidate
        return before + candidate, [], ""
    marker = candidate[: marker_end + 2]
    remainder = candidate[marker_end + 2 :]
    if not marker.startswith(_CITATION_PREFIX) or not marker.endswith("]]"):
        return before + marker, [], remainder
    evidence_id = marker[len(_CITATION_PREFIX) : -2]
    if not evidence_id or not all(
        character.isalnum() or character in "_.:-" for character in evidence_id
    ):
        return before + marker, [], remainder
    if evidence_id not in known_evidence_ids:
        return before + marker, [], remainder
    return before, [evidence_id], remainder


__all__ = ["process_citation_buffer"]
