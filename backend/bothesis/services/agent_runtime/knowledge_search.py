"""Coordinate bounded knowledge retrieval for one agent tool call."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from time import perf_counter
from typing import Any

from bothesis.agent.models import CitationReferences
from bothesis.knowledge import (
    ContextBuilder,
    Evidence,
    EvidenceContextBuilder,
    KnowledgeRetriever,
    RetrievalContext,
)
from bothesis.observability import NoopTracer, TraceSerializer, TraceSpan, Tracer
from bothesis.services.agent_runtime import (
    AgentKnowledgeSearchResult,
    MAX_KNOWLEDGE_SEARCH_QUERY_CHARACTERS,
)

_EMPTY_CONTENT = "No matching access-permitted enterprise documents were found."
_TIMEOUT_ERROR = "Knowledge search timed out. Please try again."
_FAILURE_ERROR = "Knowledge search is temporarily unavailable. Please try again."


class AgentKnowledgeSearchService:
    """Build a model-safe, citable retrieval observation for one agent step."""

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
        tracer: Tracer | None = None,
    ) -> None:
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
        self._tracer = tracer or NoopTracer()

    async def search(
        self,
        arguments: dict[str, Any],
        *,
        context: RetrievalContext,
        references: CitationReferences,
        call_id: str,
    ) -> AgentKnowledgeSearchResult:
        """Return a single bounded result for model-supplied search arguments."""

        queries, validation_error = self._validated_queries(arguments)
        if validation_error is not None:
            return AgentKnowledgeSearchResult(
                content="",
                error=validation_error,
                outcome="invalid_input",
            )

        started_at = perf_counter()
        results = await self._search_all(queries, context, call_id)
        evidence, failures = self._merged_evidence(results, references)
        duration_ms = self._duration_ms(started_at)

        built = self._context_builder.build(evidence) if evidence else None
        if built is not None and built.evidence:
            return AgentKnowledgeSearchResult(
                content=built.text,
                evidence=built.evidence,
                outcome="partial_success" if failures else "success",
                success_criteria_met=True,
                duration_ms=duration_ms,
            )
        if failures:
            timed_out = all(failure == "timeout" for failure in failures)
            return AgentKnowledgeSearchResult(
                content="",
                error=_TIMEOUT_ERROR if timed_out else _FAILURE_ERROR,
                outcome="timeout" if timed_out else "retrieval_failure",
                duration_ms=duration_ms,
            )
        return AgentKnowledgeSearchResult(
            content=_EMPTY_CONTENT,
            outcome="empty",
            success_criteria_met=False,
            duration_ms=duration_ms,
        )

    async def _search_all(
        self,
        queries: list[str],
        context: RetrievalContext,
        call_id: str,
    ) -> list[tuple[list[Evidence], str | None]]:
        """Run every query concurrently under one shared wall-clock budget."""

        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        if len(queries) == 1:
            return [await self._search_query(queries[0], context, call_id, deadline)]
        return list(
            await asyncio.gather(
                *(
                    self._search_query(query, context, call_id, deadline)
                    for query in queries
                )
            )
        )

    @staticmethod
    def _merged_evidence(
        results: list[tuple[list[Evidence], str | None]],
        references: CitationReferences,
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
                evidence.append(replace(item, id=references.reference(*identity)))
        return evidence, failures

    async def _search_query(
        self,
        query: str,
        context: RetrievalContext,
        call_id: str,
        deadline: float,
    ) -> tuple[list[Evidence], str | None]:
        started_at = perf_counter()
        with self._tracer.span(
            "knowledge.retrieve",
            attributes={"result_limit": self._result_limit, "tool_call_id": call_id},
            input=TraceSerializer.full(
                TraceSerializer.retrieval_input(
                    query=query, result_limit=self._result_limit
                )
            ),
        ) as trace:
            try:
                async with asyncio.timeout_at(deadline):
                    evidence = await self._retriever.search(
                        query,
                        limit=self._result_limit,
                        ctx=context,
                    )
            except TimeoutError:
                return [], self._failed(trace, "timeout", started_at)
            except ValueError:
                return [], self._failed(trace, "invalid_query", started_at)
            except Exception:  # noqa: BLE001 - retrieval errors are model observations
                return [], self._failed(trace, "retrieval_failure", started_at)

            trace.set_output(
                TraceSerializer.full(
                    TraceSerializer.retrieval_output(
                        outcome="success" if evidence else "empty",
                        result_count=len(evidence),
                        source_types=[
                            item.source.provider.value
                            for item in evidence
                            if item.source is not None
                        ],
                        duration_ms=self._duration_ms(started_at),
                        results=evidence,
                    )
                )
            )
            return evidence, None

    def _failed(
        self,
        trace: TraceSpan,
        category: str,
        started_at: float,
    ) -> str:
        trace.set_output(
            TraceSerializer.full(
                TraceSerializer.retrieval_output(
                    outcome=category,
                    result_count=0,
                    source_types=(),
                    duration_ms=self._duration_ms(started_at),
                )
            )
        )
        return category

    def _validated_queries(
        self, arguments: dict[str, Any]
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
            if len(query) > MAX_KNOWLEDGE_SEARCH_QUERY_CHARACTERS:
                return [], (
                    "knowledge_search queries must not exceed "
                    f"{MAX_KNOWLEDGE_SEARCH_QUERY_CHARACTERS} characters."
                )
            query_key = query.casefold()
            if query_key not in seen_queries:
                seen_queries.add(query_key)
                queries.append(query)
        return queries, None

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return round((perf_counter() - started_at) * 1_000)


__all__ = ["AgentKnowledgeSearchService"]
