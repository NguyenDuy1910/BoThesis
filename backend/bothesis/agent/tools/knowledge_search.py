"""Agent tool for retrieving already-indexed enterprise document chunks."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from time import perf_counter

from bothesis.agent.models import AgentContext, Evidence, ToolResult
from bothesis.agent.tools import AgentTool
from bothesis.knowledge.document_index import KnowledgeRetriever, RetrievedDocument
from bothesis.observability import LangfuseTracing


class KnowledgeSearchTool(AgentTool):
    """Retrieve focused, source-preserving context for the current agent run."""

    name = "knowledge_search"
    description = (
        "Search indexed company documents for evidence needed to answer a "
        "company-specific question."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A focused search query using the user's key terms.",
                "minLength": 1,
                "maxLength": 512,
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        retriever: KnowledgeRetriever,
        *,
        result_limit: int = 5,
        timeout_seconds: float = 8.0,
        max_context_characters: int = 8_000,
        max_evidence_characters: int = 1_600,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        if result_limit < 1:
            raise ValueError("result_limit must be at least one")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_context_characters < 1 or max_evidence_characters < 1:
            raise ValueError("context limits must be greater than zero")
        self._retriever = retriever
        self._result_limit = result_limit
        self._timeout_seconds = timeout_seconds
        self._max_context_characters = max_context_characters
        self._max_evidence_characters = max_evidence_characters
        self._tracing = tracing

    async def execute(self, arguments: dict[str, object], ctx: AgentContext) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                call_id="",
                content="",
                error="knowledge_search requires a non-empty query.",
                metadata={"outcome": "invalid_input", "result_count": 0, "duration_ms": 0},
            )
        normalized_query = query.strip()
        if len(normalized_query) > 512:
            return ToolResult(
                call_id="",
                content="",
                error="knowledge_search query exceeds 512 characters.",
                metadata={"outcome": "invalid_input", "result_count": 0, "duration_ms": 0},
            )

        started_at = perf_counter()
        trace_context = (
            self._tracing.retrieval(
                query=normalized_query,
                result_limit=self._result_limit,
            )
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as retrieval_trace:
            try:
                documents = await asyncio.wait_for(
                    self._retriever.search(normalized_query, limit=self._result_limit),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError:
                if retrieval_trace is not None:
                    retrieval_trace.fail(category="timeout")
                return self._failure_result(
                    started_at,
                    error="Knowledge search timed out. Please try again.",
                    category="timeout",
                )
            except ValueError:
                if retrieval_trace is not None:
                    retrieval_trace.fail(category="invalid_query")
                return self._failure_result(
                    started_at,
                    error="Knowledge search could not process that query.",
                    category="invalid_query",
                )
            except Exception:
                if retrieval_trace is not None:
                    retrieval_trace.fail(category="retrieval_failure")
                return self._failure_result(
                    started_at,
                    error="Knowledge search is temporarily unavailable. Please try again.",
                    category="retrieval_failure",
                )

            duration_ms = _duration_ms(started_at)
            if not documents:
                if retrieval_trace is not None:
                    retrieval_trace.complete(outcome="empty", result_count=0)
                return ToolResult(
                    call_id="",
                    content="No matching enterprise documents were found.",
                    metadata={"outcome": "empty", "result_count": 0, "duration_ms": duration_ms},
                )

            evidence = [
                _evidence_from_document(document, self._max_evidence_characters)
                for document in documents
            ]
            if retrieval_trace is not None:
                retrieval_trace.complete(
                    outcome="success",
                    result_count=len(evidence),
                    source_types=[document.source for document in documents if document.source],
                )
            return ToolResult(
                call_id="",
                content=_context_from_documents(documents, self._max_context_characters),
                evidence=evidence,
                metadata={
                    "outcome": "success",
                    "result_count": len(evidence),
                    "duration_ms": duration_ms,
                },
            )

    def _failure_result(
        self,
        started_at: float,
        *,
        error: str,
        category: str,
    ) -> ToolResult:
        duration_ms = _duration_ms(started_at)
        return ToolResult(
            call_id="",
            content="",
            error=error,
            metadata={"outcome": category, "result_count": 0, "duration_ms": duration_ms},
        )

def _context_from_documents(
    documents: list[RetrievedDocument],
    max_context_characters: int,
) -> str:
    blocks: list[str] = []
    remaining_characters = max_context_characters
    for document in documents:
        prefix = f"[{document.id}] {document.title}"
        if document.source:
            prefix += f"\nSource: {document.source}"
        if document.uri:
            prefix += f"\nURI: {document.uri}"
        prefix += "\nExcerpt: "
        available_content = remaining_characters - len(prefix) - 2
        if available_content <= 0:
            break
        excerpt = _clip(document.content, available_content)
        block = f"{prefix}{excerpt}"
        blocks.append(block)
        remaining_characters -= len(block) + 2
    return "Retrieved enterprise evidence:\n\n" + "\n\n".join(blocks)


def _evidence_from_document(
    document: RetrievedDocument,
    max_content_characters: int,
) -> Evidence:
    return Evidence(
        id=document.id,
        document_id=document.document_id,
        title=document.title,
        content=_clip(document.content, max_content_characters),
        section=_metadata_text(document, "section_title"),
        uri=document.uri,
        source=document.source,
        relevance_score=document.relevance_score,
    )


def _metadata_text(document: RetrievedDocument, key: str) -> str | None:
    value = document.metadata.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: max(1, limit - 1)].rstrip()}…"


def _duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1_000)
