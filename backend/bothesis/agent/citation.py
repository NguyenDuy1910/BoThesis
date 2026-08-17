"""Citation-safe final-answer projection for one conversation run."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

from bothesis.agent.models import CitationEvent, Evidence, FinalAnswerDelta


_CITATION_PREFIX = "[[cite:"
_MAX_MARKER_LENGTH = 256


class CitationRenderer:
    """Turn answer deltas into visible text and grounded citation events."""

    async def render(
        self,
        deltas: tuple[str, ...],
        evidence: Mapping[str, Evidence],
        used_evidence_ids: set[str],
    ) -> AsyncIterator[FinalAnswerDelta | CitationEvent]:
        buffer = ""
        for delta in deltas:
            buffer += delta
            events, buffer = _process_citation_buffer(buffer, evidence)
            for event in events:
                if isinstance(event, CitationEvent):
                    used_evidence_ids.add(event.evidence_id)
                yield event
        if buffer:
            yield FinalAnswerDelta(text=buffer)


def _process_citation_buffer(
    buffer: str,
    evidence: Mapping[str, Evidence],
) -> tuple[list[FinalAnswerDelta | CitationEvent], str]:
    remaining = buffer
    emitted: list[FinalAnswerDelta | CitationEvent] = []
    while remaining:
        start = remaining.find("[[")
        if start < 0:
            if remaining.endswith("["):
                emitted.append(FinalAnswerDelta(text=remaining[:-1]))
                return emitted, "["
            emitted.append(FinalAnswerDelta(text=remaining))
            return emitted, ""
        before, candidate = remaining[:start], remaining[start:]
        end = candidate.find("]]", 2)
        if end < 0:
            if candidate.startswith(_CITATION_PREFIX) and len(candidate) <= _MAX_MARKER_LENGTH:
                if before:
                    emitted.append(FinalAnswerDelta(text=before))
                return emitted, candidate
            emitted.append(FinalAnswerDelta(text=remaining))
            return emitted, ""
        marker, remaining = candidate[: end + 2], candidate[end + 2 :]
        if before:
            emitted.append(FinalAnswerDelta(text=before))
        evidence_id = marker[len(_CITATION_PREFIX) : -2]
        if (
            marker.startswith(_CITATION_PREFIX)
            and evidence_id in evidence
            and all(character.isalnum() or character in "_.:-" for character in evidence_id)
        ):
            item = evidence[evidence_id]
            emitted.append(
                CitationEvent(
                    evidence_id=evidence_id,
                    title=item.title,
                    page=item.page,
                    uri=item.uri,
                )
            )
        else:
            emitted.append(FinalAnswerDelta(text=marker))
    return emitted, ""


__all__ = ["CitationRenderer"]
