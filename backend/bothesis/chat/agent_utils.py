"""Pure transformations shared by enterprise chat orchestration."""

from __future__ import annotations

import json
from time import perf_counter

from bothesis.agent.models import (
    Evidence,
    EvidenceReference,
    ToolCall,
    ToolResult,
)


def evidence_score(evidence: Evidence) -> float:
    return evidence.relevance_score if evidence.relevance_score is not None else -1.0


def limit_tool_result(result: ToolResult, max_characters: int) -> ToolResult:
    if len(result.content) <= max_characters:
        return result
    truncated_content = f"{result.content[: max_characters - 1].rstrip()}…"
    return ToolResult(
        call_id=result.call_id,
        content=truncated_content,
        evidence=result.evidence,
        error=result.error,
        metadata=result.metadata,
    )


def result_count(result: ToolResult) -> int | None:
    value = result.metadata.get("result_count")
    return value if isinstance(value, int) else None


def result_duration(result: ToolResult) -> int | None:
    value = result.metadata.get("duration_ms")
    return value if isinstance(value, int) else None


def duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1_000)


def evidence_reference(evidence: Evidence) -> EvidenceReference:
    return EvidenceReference(
        id=evidence.id,
        document_id=evidence.document_id,
        title=evidence.title,
        page=evidence.page,
        section=evidence.section,
        uri=evidence.uri,
        source=evidence.source,
        snippet=_evidence_snippet(evidence.content),
        relevance_score=evidence.relevance_score,
    )


def _evidence_snippet(content: str, max_characters: int = 220) -> str | None:
    normalized = " ".join(content.split())
    if not normalized:
        return None
    if len(normalized) <= max_characters:
        return normalized
    return f"{normalized[: max_characters - 1].rstrip()}…"


def tool_signature(call: ToolCall) -> str:
    """Return a stable signature used to suppress repeated model tool calls."""

    arguments_value = call.arguments
    if call.name == "knowledge_search" and isinstance(call.arguments.get("query"), str):
        arguments_value = {
            **call.arguments,
            "query": " ".join(call.arguments["query"].split()).casefold(),
        }
    arguments = json.dumps(
        arguments_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{call.name}:{arguments}"


__all__ = [
    "duration_ms",
    "evidence_reference",
    "evidence_score",
    "limit_tool_result",
    "result_count",
    "result_duration",
    "tool_signature",
]
