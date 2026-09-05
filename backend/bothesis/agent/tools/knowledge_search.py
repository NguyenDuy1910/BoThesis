"""Permission-scoped retrieval of grounded enterprise knowledge."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import replace
from time import perf_counter
from typing import Any

from bothesis.agent.models import ToolContext, ToolOutput
from bothesis.agent.tools import Tool, ToolDefinition
from bothesis.knowledge import (
    ContextBuilder,
    Evidence,
    EvidenceContextBuilder,
    KnowledgeRetriever,
)
from bothesis.observability import LangfuseTracing


class KnowledgeSearch(Tool):
    """Retrieve bounded evidence that is visible to the authenticated user."""

    _MAX_QUERY_CHARACTERS = 512

    def __init__(
        self,
        retriever: KnowledgeRetriever,
        *,
        result_limit: int = 5,
        max_queries: int = 3,
        timeout_seconds: float = 8.0,
        max_context_characters: int = 8_000,
        max_evidence_characters: int = 1_600,
        context_builder: ContextBuilder | None = None,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        if result_limit < 1:
            raise ValueError("result_limit must be at least one")
        if max_queries < 1:
            raise ValueError("max_queries must be at least one")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_context_characters < 1 or max_evidence_characters < 1:
            raise ValueError("context limits must be greater than zero")

        self._retriever = retriever
        self._result_limit = result_limit
        self._max_queries = max_queries
        self._timeout_seconds = timeout_seconds
        self._context_builder = context_builder or EvidenceContextBuilder(
            max_characters=max_context_characters,
            max_evidence_characters=max_evidence_characters,
        )
        self._tracing = tracing

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="knowledge_search",
            description=(
                "Search access-permitted enterprise knowledge for source-grounded "
                "evidence. Use focused standalone queries that retain exact "
                "entities, identifiers, dates, and constraints. Results include "
                "the source references to cite."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "description": (
                            "One to three focused standalone queries. Do not use "
                            "generic terms or combine unrelated questions."
                        ),
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": self._MAX_QUERY_CHARACTERS,
                        },
                        "minItems": 1,
                        "maxItems": self._max_queries,
                    }
                },
                "required": ["queries"],
                "additionalProperties": False,
            },
            activity_label="Search knowledge base",
            activity_category="retrieval",
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolOutput:
        queries, validation_error = self._validated_queries(arguments)
        if validation_error:
            return ToolOutput(
                content="",
                error=validation_error,
                metadata={
                    "outcome": "invalid_input",
                    "result_count": 0,
                    "duration_ms": 0,
                },
            )
        if not isinstance(self._retriever, KnowledgeRetriever):
            return ToolOutput(
                content="",
                error="Knowledge search is temporarily unavailable. Please try again.",
                metadata={
                    "outcome": "configuration_error",
                    "result_count": 0,
                    "duration_ms": 0,
                },
            )

        started_at = perf_counter()
        results = await asyncio.gather(
            *(self._search_query(query, ctx) for query in queries),
        )
        evidence: list[Evidence] = []
        failures: list[str] = []
        seen_evidence_ids: set[str] = set()
        for query_evidence, failure in results:
            if failure:
                failures.append(failure)
            for item in query_evidence:
                if item.id in seen_evidence_ids:
                    continue
                seen_evidence_ids.add(item.id)
                # The compact reference is what the model is allowed to cite,
                # and it is assigned before the context is built so the model
                # never sees an Item or chunk identifier it could echo back.
                evidence.append(
                    replace(
                        item,
                        id=ctx.references.reference(item.item_id, item.chunk_id),
                    )
                )

        duration_ms = self._duration_ms(started_at)
        if not evidence:
            if failures:
                outcome = (
                    "timeout"
                    if all(failure == "timeout" for failure in failures)
                    else "retrieval_failure"
                )
                message = (
                    "Knowledge search timed out. Please try again."
                    if outcome == "timeout"
                    else "Knowledge search is temporarily unavailable. Please try again."
                )
                return ToolOutput(
                    content="",
                    error=message,
                    metadata={
                        "outcome": outcome,
                        "result_count": 0,
                        "duration_ms": duration_ms,
                    },
                )
            return ToolOutput(
                content="No matching access-permitted enterprise documents were found.",
                metadata={
                    "outcome": "empty",
                    "result_count": 0,
                    "success_criteria_met": False,
                    "duration_ms": duration_ms,
                },
            )

        context = self._context_builder.build(evidence)
        return ToolOutput(
            content=context.text,
            evidence=list(context.evidence),
            metadata={
                "outcome": "partial_success" if failures else "success",
                "result_count": len(context.evidence),
                "success_criteria_met": True,
                "duration_ms": duration_ms,
            },
        )

    async def _search_query(
        self,
        query: str,
        ctx: ToolContext,
    ) -> tuple[list[Evidence], str | None]:
        started_at = perf_counter()
        trace_context = (
            self._tracing.retrieval(
                query=query,
                result_limit=self._result_limit,
                ctx=ctx.agent_context,
            )
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as retrieval_trace:
            try:
                evidence = await asyncio.wait_for(
                    self._retriever.search(
                        query,
                        limit=self._result_limit,
                        ctx=ctx.agent_context,
                    ),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError:
                if retrieval_trace is not None:
                    retrieval_trace.fail(
                        category="timeout",
                        duration_ms=self._duration_ms(started_at),
                    )
                return [], "timeout"
            except ValueError:
                if retrieval_trace is not None:
                    retrieval_trace.fail(
                        category="invalid_query",
                        duration_ms=self._duration_ms(started_at),
                    )
                return [], "invalid_query"
            except Exception:  # noqa: BLE001 - retrieval errors are model observations
                if retrieval_trace is not None:
                    retrieval_trace.fail(
                        category="retrieval_failure",
                        duration_ms=self._duration_ms(started_at),
                    )
                return [], "retrieval_failure"

            if retrieval_trace is not None:
                retrieval_trace.complete(
                    outcome="success" if evidence else "empty",
                    result_count=len(evidence),
                    source_types=[
                        item.source.provider.value
                        for item in evidence
                        if item.source is not None
                    ],
                    results=evidence,
                    duration_ms=self._duration_ms(started_at),
                )
            return evidence, None

    def _validated_queries(
        self,
        arguments: dict[str, Any],
    ) -> tuple[list[str], str | None]:
        raw_queries = arguments.get("queries")
        if not isinstance(raw_queries, list) or not raw_queries:
            return [], "knowledge_search requires at least one query."
        if len(raw_queries) > self._max_queries:
            return [], f"knowledge_search accepts at most {self._max_queries} queries."

        queries: list[str] = []
        seen_queries: set[str] = set()
        for raw_query in raw_queries:
            if not isinstance(raw_query, str):
                return [], "knowledge_search queries must be strings."
            query = " ".join(raw_query.split())
            if not query:
                return [], "knowledge_search queries must not be empty."
            if len(query) > self._MAX_QUERY_CHARACTERS:
                return [], "knowledge_search queries must not exceed 512 characters."
            query_key = query.casefold()
            if query_key not in seen_queries:
                seen_queries.add(query_key)
                queries.append(query)
        return queries, None

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return round((perf_counter() - started_at) * 1_000)


__all__ = ["KnowledgeSearch"]
