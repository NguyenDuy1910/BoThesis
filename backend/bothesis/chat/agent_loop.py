"""Dynamic, streaming enterprise knowledge-agent orchestration."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any

from bothesis.agent.capabilities import (
    CapabilityExecutionError,
    CapabilityResult,
    EvidenceSynthesis,
    KnowledgeCapabilityExecutor,
    QueryList,
    QueryRewrite,
    RetrievalEvaluation,
    SynthesizedFact,
    compact_json,
)
from bothesis.agent.models import (
    AgentContext,
    AgentEvent,
    CitationAvailable,
    CitationEvent,
    ConversationMessage,
    Evidence,
    EvidenceReference,
    GenerationCompleted,
    GenerationStarted,
    MessageDelta,
    ModelTurn,
    RunCompleted,
    RunFailed,
    RunStarted,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolCompleted,
    ToolResult,
    ToolStarted,
    TurnCompleted,
    TurnDone,
    TurnStarted,
)
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.transports.base import LLMTransport, LLMTransportError
from bothesis.observability import AgentRunTrace, LangfuseTracing

_CITATION_PREFIX = "[[cite:"
_MAX_CITATION_MARKER_LENGTH = 256
_MULTI_NEED_PATTERN = re.compile(
    r"\b(and|versus|vs\.?|compare|comparison|difference|relationship|"
    r"both|each|respectively|as well as)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_QUERY_PATTERN = re.compile(
    r"^(this|that|it|these|those|them|more|why|how|what about that)\??$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class KnowledgeAgentState:
    """Useful observable state retained for one request; no private reasoning."""

    current_query: str
    generated_search_queries: list[str] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    missing_evidence: list[str] = field(default_factory=list)
    source_conflicts: list[str] = field(default_factory=list)
    executed_queries: set[str] = field(default_factory=set)
    used_evidence_ids: set[str] = field(default_factory=set)
    retrieval_round: int = 0
    completion_status: str = "running"
    turn: int = 0
    step: int = 0
    capability_call_count: int = 0
    tool_call_count: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    answer_character_count: int = 0


@dataclass(frozen=True, slots=True)
class _StreamCompleted:
    turn: ModelTurn
    duration_ms: int


class _TurnAccumulator:
    def __init__(self) -> None:
        self._text: list[str] = []
        self._finish_reason: str | None = None
        self._model: str | None = None
        self._usage: dict[str, int] = {}

    def feed(self, event: TextDelta | ToolCallDelta | TurnDone) -> None:
        if isinstance(event, TextDelta):
            self._text.append(event.delta)
            return
        if isinstance(event, ToolCallDelta):
            raise CapabilityExecutionError(
                "a response capability attempted an unavailable tool call"
            )
        if event.tool_calls:
            raise CapabilityExecutionError(
                "a response capability attempted an unavailable tool call"
            )
        self._finish_reason = event.finish_reason
        self._model = event.model
        self._usage = event.usage

    def result(self) -> ModelTurn:
        return ModelTurn(
            text="".join(self._text),
            tool_calls=[],
            finish_reason=self._finish_reason,
            model=self._model,
            usage=self._usage,
        )


class AgentLoop:
    """Run only the knowledge capabilities required by the current request."""

    def __init__(
        self,
        transport: LLMTransport,
        registry: ToolRegistry,
        *,
        capabilities: KnowledgeCapabilityExecutor | None = None,
        max_retrieval_rounds: int = 2,
        max_retrieval_queries: int = 3,
        max_capability_calls: int = 8,
        max_tool_calls: int = 6,
        max_history_messages: int = 8,
        max_history_characters: int = 8_000,
        max_tool_result_characters: int = 10_000,
        max_evidence_context_characters: int = 12_000,
        max_user_message_characters: int = 4_000,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        if max_retrieval_rounds < 1:
            raise ValueError("max_retrieval_rounds must be at least one")
        if max_retrieval_queries < 1:
            raise ValueError("max_retrieval_queries must be at least one")
        if max_capability_calls < 2:
            raise ValueError("max_capability_calls must be at least two")
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least one")
        if (
            min(
                max_history_messages,
                max_history_characters,
                max_tool_result_characters,
                max_evidence_context_characters,
                max_user_message_characters,
            )
            < 1
        ):
            raise ValueError("agent limits must be at least one")
        self._transport = transport
        self._registry = registry
        self._tracing = tracing
        self._capabilities = capabilities or KnowledgeCapabilityExecutor(
            transport,
            tracing=tracing,
        )
        self._max_retrieval_rounds = max_retrieval_rounds
        self._max_retrieval_queries = max_retrieval_queries
        self._max_capability_calls = max_capability_calls
        self._max_tool_calls = max_tool_calls
        self._max_history_messages = max_history_messages
        self._max_history_characters = max_history_characters
        self._max_tool_result_characters = max_tool_result_characters
        self._max_evidence_context_characters = max_evidence_context_characters
        self._max_user_message_characters = max_user_message_characters

    async def run_stream(
        self, user_message: str, ctx: AgentContext
    ) -> AsyncIterator[AgentEvent]:
        normalized_message = user_message.strip()
        if not normalized_message:
            yield RunFailed(error="message must not be empty")
            return
        if len(normalized_message) > self._max_user_message_characters:
            yield RunFailed(error="message exceeds the allowed length")
            return
        if not ctx.tenant_id or not ctx.user_id:
            yield RunFailed(error="tenant and user context are required")
            return

        trace_context = (
            self._tracing.agent_run(user_message=normalized_message, ctx=ctx)
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as run_trace:
            try:
                async for event in self._run_validated_stream(
                    normalized_message,
                    ctx,
                    run_trace,
                ):
                    yield event
            except CapabilityExecutionError:
                if run_trace is not None:
                    run_trace.fail(stage="capability")
                yield RunFailed(error="model response failed")

    async def _run_validated_stream(
        self,
        normalized_message: str,
        ctx: AgentContext,
        run_trace: AgentRunTrace | None,
    ) -> AsyncIterator[AgentEvent]:
        started_at = perf_counter()
        state = KnowledgeAgentState(current_query=normalized_message)
        conversation = self._conversation_context(ctx.history)
        yield RunStarted(
            conversation_id=ctx.conversation_id,
            request_id=ctx.request_id,
        )

        if _requires_clarification(normalized_message, ctx.history):
            async for event in self._stream_final_capability(
                capability="clarification",
                values={"conversation": conversation, "query": normalized_message},
                ctx=ctx,
                state=state,
                turn_number=0,
            ):
                if isinstance(event, _StreamCompleted):
                    completed_turn = event.turn
                else:
                    yield event
            async for event in self._complete_run(
                state=state,
                completed_turn=completed_turn,
                started_at=started_at,
                run_trace=run_trace,
            ):
                yield event
            return

        yield TurnStarted(turn=0)
        yield GenerationStarted(turn=0)
        planning_started_ms = state.model_duration_ms
        await self._rewrite_query(state, normalized_message, conversation, ctx)
        complex_request = _needs_decomposition(state.current_query)
        queries = await self._initial_queries(state, ctx, complex_request)
        planning_duration_ms = state.model_duration_ms - planning_started_ms
        yield GenerationCompleted(
            turn=0,
            generation_kind="next_step",
            finish_reason="capability_complete",
            tool_call_count=len(queries),
            selected_tools=["knowledge_search"] if queries else [],
            duration_ms=planning_duration_ms,
        )
        async for event in self._retrieve_queries(
            queries=queries,
            ctx=ctx,
            state=state,
        ):
            yield event
        yield TurnCompleted(turn=0, outcome="tool")

        evaluation = await self._evaluate_when_needed(
            state=state,
            ctx=ctx,
            complex_request=complex_request,
        )
        while (
            evaluation is not None
            and evaluation.requires_additional_retrieval
            and state.missing_evidence
            and state.retrieval_round < self._max_retrieval_rounds
            and state.tool_call_count < self._max_tool_calls
        ):
            state.turn += 1
            yield TurnStarted(turn=state.turn)
            yield GenerationStarted(turn=state.turn)
            refinement_started_ms = state.model_duration_ms
            refined_queries = await self._refine_queries(state, ctx)
            yield GenerationCompleted(
                turn=state.turn,
                generation_kind="next_step",
                finish_reason="capability_complete",
                tool_call_count=len(refined_queries),
                selected_tools=["knowledge_search"] if refined_queries else [],
                duration_ms=state.model_duration_ms - refinement_started_ms,
            )
            if not refined_queries:
                yield TurnCompleted(turn=state.turn, outcome="tool")
                break
            async for event in self._retrieve_queries(
                queries=refined_queries,
                ctx=ctx,
                state=state,
            ):
                yield event
            yield TurnCompleted(turn=state.turn, outcome="tool")
            evaluation = await self._evaluate_evidence(state, ctx)

        synthesis = await self._synthesize_when_needed(
            state=state,
            ctx=ctx,
            complex_request=complex_request,
        )
        state.turn += 1
        answer_evidence = (
            _evidence_reference_prompt_data(state.evidence.values())
            if synthesis is not None
            else self._evidence_prompt_data(state)
        )
        answer_values = {
            "question": state.current_query,
            "evidence": compact_json(answer_evidence),
            "synthesis": compact_json(_synthesis_prompt_data(synthesis)),
            "missing_information": compact_json(state.missing_evidence),
            "source_conflicts": compact_json(state.source_conflicts),
        }
        async for event in self._stream_final_capability(
            capability="answer_grounded",
            values=answer_values,
            ctx=ctx,
            state=state,
            turn_number=state.turn,
        ):
            if isinstance(event, _StreamCompleted):
                completed_turn = event.turn
            else:
                yield event
        async for event in self._complete_run(
            state=state,
            completed_turn=completed_turn,
            started_at=started_at,
            run_trace=run_trace,
        ):
            yield event

    async def _rewrite_query(
        self,
        state: KnowledgeAgentState,
        query: str,
        conversation: str,
        ctx: AgentContext,
    ) -> None:
        try:
            result = await self._structured_capability(
                state,
                ctx,
                "query_rewrite",
                QueryRewrite,
                {"conversation": conversation, "query": query},
            )
        except CapabilityExecutionError:
            return
        state.current_query = result.value.query.strip()

    async def _initial_queries(
        self,
        state: KnowledgeAgentState,
        ctx: AgentContext,
        complex_request: bool,
    ) -> list[str]:
        if not complex_request:
            queries = [state.current_query]
        else:
            try:
                decomposition = await self._structured_capability(
                    state,
                    ctx,
                    "query_decomposition",
                    QueryList,
                    {
                        "query": state.current_query,
                        "maximum_queries": self._max_retrieval_queries * 2,
                    },
                )
                queries = _normalize_queries(decomposition.value.queries)
            except CapabilityExecutionError:
                queries = [state.current_query]
        if not queries:
            queries = [state.current_query]
        if len(queries) > self._max_retrieval_queries:
            try:
                plan = await self._structured_capability(
                    state,
                    ctx,
                    "retrieval_plan",
                    QueryList,
                    {
                        "question": state.current_query,
                        "candidate_queries": compact_json(queries),
                        "maximum_queries": self._max_retrieval_queries,
                    },
                    retrieval_query_count=len(queries),
                )
                planned = _normalize_queries(plan.value.queries)
                if planned:
                    queries = planned
            except CapabilityExecutionError:
                pass
        return queries[: self._max_retrieval_queries]

    async def _evaluate_when_needed(
        self,
        *,
        state: KnowledgeAgentState,
        ctx: AgentContext,
        complex_request: bool,
    ) -> RetrievalEvaluation | None:
        if not complex_request and state.evidence:
            return None
        return await self._evaluate_evidence(state, ctx)

    async def _evaluate_evidence(
        self,
        state: KnowledgeAgentState,
        ctx: AgentContext,
    ) -> RetrievalEvaluation | None:
        try:
            result = await self._structured_capability(
                state,
                ctx,
                "retrieval_evaluate",
                RetrievalEvaluation,
                {
                    "question": state.current_query,
                    "searched_queries": compact_json(state.generated_search_queries),
                    "evidence": compact_json(self._evidence_prompt_data(state)),
                    "retrieval_round": state.retrieval_round,
                },
                retrieval_round=state.retrieval_round,
                retrieval_query_count=len(state.generated_search_queries),
            )
        except CapabilityExecutionError:
            return None
        state.missing_evidence = result.value.missing
        state.source_conflicts = result.value.conflicts
        return result.value

    async def _refine_queries(
        self,
        state: KnowledgeAgentState,
        ctx: AgentContext,
    ) -> list[str]:
        remaining_tool_calls = self._max_tool_calls - state.tool_call_count
        maximum_queries = min(self._max_retrieval_queries, remaining_tool_calls)
        if maximum_queries <= 0:
            return []
        try:
            result = await self._structured_capability(
                state,
                ctx,
                "retrieval_refine",
                QueryList,
                {
                    "question": state.current_query,
                    "missing_evidence": compact_json(state.missing_evidence),
                    "previous_queries": compact_json(state.generated_search_queries),
                    "maximum_queries": maximum_queries,
                },
                retrieval_round=state.retrieval_round,
                retrieval_query_count=maximum_queries,
            )
        except CapabilityExecutionError:
            return []
        return _normalize_queries(
            result.value.queries,
            excluded=state.executed_queries,
        )[:maximum_queries]

    async def _synthesize_when_needed(
        self,
        *,
        state: KnowledgeAgentState,
        ctx: AgentContext,
        complex_request: bool,
    ) -> EvidenceSynthesis | None:
        if not state.evidence or (not complex_request and state.retrieval_round == 1):
            return None
        try:
            result = await self._structured_capability(
                state,
                ctx,
                "evidence_synthesis",
                EvidenceSynthesis,
                {
                    "question": state.current_query,
                    "evidence": compact_json(self._evidence_prompt_data(state)),
                },
                retrieval_round=state.retrieval_round,
                retrieval_query_count=len(state.generated_search_queries),
            )
        except CapabilityExecutionError:
            return None
        synthesis = _ground_synthesis(result.value, set(state.evidence))
        state.missing_evidence = _merge_unique(
            state.missing_evidence,
            synthesis.missing,
        )
        state.source_conflicts = _merge_unique(
            state.source_conflicts,
            synthesis.conflicts,
        )
        return synthesis

    async def _structured_capability(
        self,
        state: KnowledgeAgentState,
        ctx: AgentContext,
        capability: str,
        output_model: type[QueryRewrite]
        | type[QueryList]
        | type[RetrievalEvaluation]
        | type[EvidenceSynthesis],
        values: dict[str, object],
        *,
        retrieval_round: int = 0,
        retrieval_query_count: int = 0,
    ) -> CapabilityResult[Any]:
        if state.capability_call_count >= self._max_capability_calls - 1:
            raise CapabilityExecutionError("capability-call limit reached")
        state.capability_call_count += 1
        state.step += 1
        result = await self._capabilities.structured(
            capability,
            output_model,
            values=values,
            ctx=ctx,
            step=state.step,
            retrieval_round=retrieval_round,
            retrieval_query_count=retrieval_query_count,
        )
        state.model_duration_ms += result.duration_ms
        return result

    async def _retrieve_queries(
        self,
        *,
        queries: list[str],
        ctx: AgentContext,
        state: KnowledgeAgentState,
    ) -> AsyncIterator[AgentEvent]:
        normalized_queries = _normalize_queries(
            queries,
            excluded=state.executed_queries,
        )
        remaining_tool_calls = self._max_tool_calls - state.tool_call_count
        normalized_queries = normalized_queries[:remaining_tool_calls]
        if not normalized_queries:
            return

        state.retrieval_round += 1
        state.generated_search_queries.extend(normalized_queries)
        state.executed_queries.update(query.casefold() for query in normalized_queries)
        calls: list[tuple[ToolCall, AgentContext]] = []
        query_count = len(normalized_queries)
        for index, query in enumerate(normalized_queries, start=1):
            state.step += 1
            call = ToolCall(
                call_id=f"retrieval-{state.retrieval_round}-{index}",
                name="knowledge_search",
                arguments={"query": query},
            )
            execution_context = replace(
                ctx,
                trace_step=state.step,
                retrieval_round=state.retrieval_round,
                retrieval_query_count=query_count,
            )
            calls.append((call, execution_context))
            yield ToolStarted(
                call_id=call.call_id,
                name=call.name,
                arguments=call.arguments,
            )

        retrieval_started_at = perf_counter()
        results = await asyncio.gather(
            *(
                self._registry.execute(call, execution_context)
                for call, execution_context in calls
            )
        )
        state.tool_duration_ms += _duration_ms(retrieval_started_at)
        state.tool_call_count += len(calls)

        for (call, _), raw_result in zip(calls, results, strict=True):
            result = _limit_tool_result(
                raw_result,
                self._max_tool_result_characters,
            )
            for evidence in result.evidence:
                existing = state.evidence.get(evidence.id)
                if existing is None:
                    state.evidence[evidence.id] = evidence
                    yield CitationAvailable(evidence=_evidence_reference(evidence))
                elif _evidence_score(evidence) > _evidence_score(existing):
                    state.evidence[evidence.id] = evidence
            yield ToolCompleted(
                call_id=call.call_id,
                name=call.name,
                error=result.error,
                duration_ms=_result_duration(result),
                result_count=_result_count(result),
            )

    async def _stream_final_capability(
        self,
        *,
        capability: str,
        values: dict[str, object],
        ctx: AgentContext,
        state: KnowledgeAgentState,
        turn_number: int,
    ) -> AsyncIterator[AgentEvent | _StreamCompleted]:
        if state.capability_call_count >= self._max_capability_calls:
            raise CapabilityExecutionError("capability-call limit reached")
        state.capability_call_count += 1
        state.step += 1
        yield TurnStarted(turn=turn_number)
        yield GenerationStarted(turn=turn_number)
        prompt = self._capabilities.render(capability, **values)
        accumulator = _TurnAccumulator()
        citation_buffer = ""
        started_at = perf_counter()
        trace_context = (
            self._tracing.capability(
                capability=capability,
                prompt=prompt,
                ctx=ctx,
                step=state.step,
                retrieval_round=state.retrieval_round,
                retrieval_query_count=len(state.generated_search_queries),
            )
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as capability_trace:
            try:
                async for stream_event in self._transport.stream_turn(
                    [{"role": "user", "content": prompt}],
                ):
                    accumulator.feed(stream_event)
                    if not isinstance(stream_event, TextDelta):
                        continue
                    if capability_trace is not None:
                        capability_trace.mark_first_token()
                    if capability == "answer_grounded":
                        citation_buffer += stream_event.delta
                        async for event in self._emit_citation_aware_text(
                            citation_buffer,
                            state.evidence,
                        ):
                            if isinstance(event, _CitationCarry):
                                citation_buffer = event.value
                            else:
                                if isinstance(event, MessageDelta):
                                    state.answer_character_count += len(event.text)
                                elif isinstance(event, CitationEvent):
                                    state.used_evidence_ids.add(event.evidence_id)
                                yield event
                    else:
                        state.answer_character_count += len(stream_event.delta)
                        yield MessageDelta(text=stream_event.delta)
            except LLMTransportError as exc:
                if capability_trace is not None:
                    capability_trace.fail(
                        category="transport_error",
                        duration_ms=_duration_ms(started_at),
                    )
                raise CapabilityExecutionError(f"{capability} stream failed") from exc
            except CapabilityExecutionError as exc:
                if capability_trace is not None:
                    capability_trace.fail(
                        category="invalid_response",
                        duration_ms=_duration_ms(started_at),
                    )
                raise CapabilityExecutionError(f"{capability} stream failed") from exc
            completed_turn = accumulator.result()
            duration_ms = _duration_ms(started_at)
            if capability_trace is not None:
                capability_trace.complete(
                    response=completed_turn,
                    output=completed_turn.text,
                    duration_ms=duration_ms,
                )
        state.model_duration_ms += duration_ms
        if citation_buffer:
            state.answer_character_count += len(citation_buffer)
            yield MessageDelta(text=citation_buffer)
        yield GenerationCompleted(
            turn=turn_number,
            generation_kind="final_response",
            finish_reason=completed_turn.finish_reason,
            tool_call_count=0,
            selected_tools=[],
            duration_ms=duration_ms,
        )
        yield _StreamCompleted(turn=completed_turn, duration_ms=duration_ms)

    async def _complete_run(
        self,
        *,
        state: KnowledgeAgentState,
        completed_turn: ModelTurn,
        started_at: float,
        run_trace: AgentRunTrace | None,
    ) -> AsyncIterator[AgentEvent]:
        state.completion_status = "completed"
        yield TurnCompleted(turn=state.turn, outcome="final")
        run_duration_ms = _duration_ms(started_at)
        if run_trace is not None:
            run_trace.complete(
                answer=completed_turn.text,
                answer_characters=state.answer_character_count,
                turn_count=state.turn + 1,
                tool_call_count=state.tool_call_count,
                sources_found=len(state.evidence),
                sources_used=len(state.used_evidence_ids),
            )
        yield RunCompleted(
            duration_ms=run_duration_ms,
            model_duration_ms=state.model_duration_ms,
            tool_duration_ms=state.tool_duration_ms,
            tool_call_count=state.tool_call_count,
        )

    def _conversation_context(
        self,
        history: tuple[ConversationMessage, ...],
    ) -> str:
        remaining_characters = self._max_history_characters
        bounded_messages: list[dict[str, str]] = []
        for message in reversed(history[-self._max_history_messages :]):
            content = message.content.strip()
            if not content or remaining_characters <= 0:
                continue
            content = content[-remaining_characters:]
            bounded_messages.append({"role": message.role, "content": content})
            remaining_characters -= len(content)
        return compact_json(list(reversed(bounded_messages)))

    def _evidence_prompt_data(
        self,
        state: KnowledgeAgentState,
    ) -> list[dict[str, Any]]:
        return _evidence_prompt_data(
            state.evidence.values(),
            max_characters=self._max_evidence_context_characters,
        )

    async def _emit_citation_aware_text(
        self,
        buffer: str,
        evidence: Mapping[str, Evidence],
    ) -> AsyncIterator[MessageDelta | CitationEvent | _CitationCarry]:
        remaining = buffer
        known_ids = set(evidence)
        while remaining:
            text, evidence_ids, next_remaining = _parse_citations(remaining, known_ids)
            if text:
                yield MessageDelta(text=text)
            for evidence_id in evidence_ids:
                item = evidence[evidence_id]
                yield CitationEvent(
                    evidence_id=evidence_id,
                    title=item.title,
                    page=item.page,
                    uri=item.uri,
                )
            if next_remaining == remaining:
                yield _CitationCarry(next_remaining)
                return
            remaining = next_remaining
        yield _CitationCarry("")


@dataclass(frozen=True, slots=True)
class _CitationCarry:
    value: str


def _requires_clarification(
    query: str,
    history: tuple[ConversationMessage, ...],
) -> bool:
    normalized = " ".join(query.split())
    return not history and bool(_AMBIGUOUS_QUERY_PATTERN.fullmatch(normalized))


def _needs_decomposition(query: str) -> bool:
    return query.count("?") > 1 or bool(_MULTI_NEED_PATTERN.search(query))


def _normalize_queries(
    queries: list[str],
    *,
    excluded: set[str] | None = None,
) -> list[str]:
    excluded_keys = excluded or set()
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_query in queries:
        query = " ".join(raw_query.split()).strip()
        if not query:
            continue
        query = query[:512].rstrip()
        key = query.casefold()
        if key in seen or key in excluded_keys:
            continue
        seen.add(key)
        normalized.append(query)
    return normalized


def _evidence_prompt_data(
    evidence: Iterable[Evidence],
    *,
    max_characters: int,
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    characters = 0
    ordered_evidence = sorted(evidence, key=_evidence_score, reverse=True)
    for item in ordered_evidence:
        candidate = {
            "id": item.id,
            "document_id": item.document_id,
            "title": item.title,
            "content": item.content,
            "page": item.page,
            "section": item.section,
            "uri": item.uri,
            "source": item.source,
            "relevance_score": item.relevance_score,
        }
        candidate_characters = len(compact_json(candidate))
        if payload and characters + candidate_characters > max_characters:
            break
        payload.append(candidate)
        characters += candidate_characters
    return payload


def _evidence_reference_prompt_data(
    evidence: Iterable[Evidence],
) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "document_id": item.document_id,
            "title": item.title,
            "page": item.page,
            "section": item.section,
            "uri": item.uri,
            "source": item.source,
        }
        for item in evidence
    ]


def _evidence_score(evidence: Evidence) -> float:
    return evidence.relevance_score if evidence.relevance_score is not None else -1.0


def _ground_synthesis(
    synthesis: EvidenceSynthesis,
    known_evidence_ids: set[str],
) -> EvidenceSynthesis:
    facts: list[SynthesizedFact] = []
    for fact in synthesis.facts:
        evidence_ids = [
            evidence_id
            for evidence_id in fact.evidence_ids
            if evidence_id in known_evidence_ids
        ]
        if evidence_ids:
            facts.append(SynthesizedFact(claim=fact.claim, evidence_ids=evidence_ids))
    return EvidenceSynthesis(
        facts=facts,
        conflicts=synthesis.conflicts,
        missing=synthesis.missing,
    )


def _synthesis_prompt_data(
    synthesis: EvidenceSynthesis | None,
) -> dict[str, Any]:
    return synthesis.model_dump(mode="json") if synthesis is not None else {}


def _merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    seen = {item.casefold() for item in existing}
    merged = list(existing)
    for item in additions:
        if item.casefold() not in seen:
            seen.add(item.casefold())
            merged.append(item)
    return merged


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


def _limit_tool_result(result: ToolResult, max_characters: int) -> ToolResult:
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


def _result_count(result: ToolResult) -> int | None:
    value = result.metadata.get("result_count")
    return value if isinstance(value, int) else None


def _result_duration(result: ToolResult) -> int | None:
    value = result.metadata.get("duration_ms")
    return value if isinstance(value, int) else None


def _duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1_000)


def _evidence_reference(evidence: Evidence) -> EvidenceReference:
    return EvidenceReference(
        id=evidence.id,
        document_id=evidence.document_id,
        title=evidence.title,
        page=evidence.page,
        section=evidence.section,
        uri=evidence.uri,
        source=evidence.source,
        relevance_score=evidence.relevance_score,
    )
