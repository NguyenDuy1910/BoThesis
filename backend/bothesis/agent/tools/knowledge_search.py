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
from bothesis.observability import LangfuseTracing, RetrievalTrace


_EMPTY_CONTENT = "No matching access-permitted enterprise documents were found."
_TIMEOUT_ERROR = "Knowledge search timed out. Please try again."
_FAILURE_ERROR = "Knowledge search is temporarily unavailable. Please try again."


class KnowledgeSearch(Tool):
    """Retrieve bounded evidence that is visible to the authenticated user."""

    _MAX_QUERY_CHARACTERS = 512

    def __init__(
        self,
        retriever: KnowledgeRetriever,
        *,
        result_limit: int = 5,
        max_queries: int = 3,
        timeout_seconds: float = 25.0,
        max_context_characters: int = 8_000,
        max_evidence_characters: int = 1_600,
        context_builder: ContextBuilder | None = None,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        # The retrieval boundary is checked once here rather than on every
        # execution: a misconfigured runtime must fail at wiring time, not be
        # reported to the model as a per-call tool failure.
        if not isinstance(retriever, KnowledgeRetriever):
            raise TypeError("retriever must implement the KnowledgeRetriever protocol")
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
        # The declaration is fixed once the limits are known, and the runtime
        # reads it on every model turn, tool call, and text-payload check.
        self._definition = self._build_definition()

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def _build_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="knowledge_search",
            description=(
                "Search access-permitted enterprise knowledge base for source-grounded "
                "evidence. ONLY use this tool when you need enterprise-specific "
                "information. Use focused, specific queries with exact entity names, "
                "identifiers, or dates. If the query is too vague or generic, ask "
                "the user for clarification BEFORE using this tool. Results include "
                "the source references to cite. If no results are found, explicitly "
                "tell the user that information was not found in the knowledge base - "
                "never fabricate an answer."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "description": (
                            "One to three focused standalone queries with specific details. "
                            "Each query must be specific and independently searchable. "
                            "Do not use generic terms (like 'information', 'details', 'company') "
                            "without specific context. Do not combine unrelated questions. "
                            "Use exact names, identifiers, dates, project codes when available. "
                            "If you only have a vague concept, ask the user for more specifics "
                            "instead of searching with generic terms."
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
        if validation_error is not None:
            return ToolOutput(
                content="",
                error=validation_error,
                metadata={
                    "outcome": "invalid_input",
                    "result_count": 0,
                    "duration_ms": 0,
                },
            )

        started_at = perf_counter()
        results = await self._search_all(queries, ctx)
        evidence, failures = self._merged_evidence(results, ctx)
        duration_ms = self._duration_ms(started_at)

        context = self._context_builder.build(evidence) if evidence else None
        if context is not None and context.evidence:
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
        if failures:
            # Reaching here means no query produced citable content, so the
            # failure is the whole outcome rather than a partial one.
            timed_out = all(failure == "timeout" for failure in failures)
            return ToolOutput(
                content="",
                error=_TIMEOUT_ERROR if timed_out else _FAILURE_ERROR,
                metadata={
                    "outcome": "timeout" if timed_out else "retrieval_failure",
                    "result_count": 0,
                    "duration_ms": duration_ms,
                },
            )
        return ToolOutput(
            content=_EMPTY_CONTENT,
            metadata={
                "outcome": "empty",
                "result_count": 0,
                "success_criteria_met": False,
                "duration_ms": duration_ms,
            },
        )

    async def _search_all(
        self,
        queries: list[str],
        ctx: ToolContext,
    ) -> list[tuple[list[Evidence], str | None]]:
        """Run every query concurrently under one shared wall-clock budget."""

        # A single deadline bounds the whole call: without it, queries dispatched
        # behind a saturated retrieval pool each restart their own budget and the
        # tool can outlive the timeout the runtime was promised.
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        if len(queries) == 1:
            return [await self._search_query(queries[0], ctx, deadline)]
        return list(
            await asyncio.gather(
                *(self._search_query(query, ctx, deadline) for query in queries)
            )
        )

    def _merged_evidence(
        self,
        results: list[tuple[list[Evidence], str | None]],
        ctx: ToolContext,
    ) -> tuple[list[Evidence], list[str]]:
        """Collapse per-query results into one deduplicated, citable ranking."""

        evidence: list[Evidence] = []
        failures: list[str] = []
        seen: set[tuple[str, str]] = set()
        for query_evidence, failure in results:
            if failure is not None:
                failures.append(failure)
                continue
            for item in query_evidence:
                identity = (item.item_id, item.chunk_id)
                if identity in seen:
                    continue
                seen.add(identity)
                # The compact reference is what the model is allowed to cite,
                # and it is assigned before the context is built so the model
                # never sees an Item or chunk identifier it could echo back.
                evidence.append(replace(item, id=ctx.references.reference(*identity)))
        return evidence, failures

    async def _search_query(
        self,
        query: str,
        ctx: ToolContext,
        deadline: float,
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
                async with asyncio.timeout_at(deadline):
                    evidence = await self._retriever.search(
                        query,
                        limit=self._result_limit,
                        ctx=ctx.agent_context,
                    )
            except TimeoutError:
                return [], self._failed(retrieval_trace, "timeout", started_at)
            except ValueError:
                return [], self._failed(retrieval_trace, "invalid_query", started_at)
            except Exception:  # noqa: BLE001 - retrieval errors are model observations
                return [], self._failed(retrieval_trace, "retrieval_failure", started_at)

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

    def _failed(
        self,
        trace: RetrievalTrace | None,
        category: str,
        started_at: float,
    ) -> str:
        if trace is not None:
            trace.fail(category=category, duration_ms=self._duration_ms(started_at))
        return category

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
                return [], (
                    "knowledge_search queries must not exceed "
                    f"{self._MAX_QUERY_CHARACTERS} characters."
                )
            query_key = query.casefold()
            if query_key not in seen_queries:
                seen_queries.add(query_key)
                queries.append(query)
        return queries, None

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return round((perf_counter() - started_at) * 1_000)


__all__ = ["KnowledgeSearch"]
