"""Langfuse tracing for the chat and retrieval pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from bothesis.agent.models import AgentContext, Evidence, ModelTurn, ToolResult
from bothesis.agent.transports.base import LLMResponse

log = logging.getLogger(__name__)


class _Observation(Protocol):
    def update(self, **kwargs: Any) -> Any: ...


@dataclass(slots=True)
class AgentRunTrace:
    """Controlled updates for one chat-turn trace."""

    _observation: _Observation
    _finished: bool = False

    def complete(
        self,
        *,
        answer: str,
        answer_characters: int,
        turn_count: int,
        tool_call_count: int,
        sources_found: int,
        sources_used: int,
    ) -> None:
        _safe_update(
            self._observation,
            output=answer,
            metadata={
                "status": "completed",
                "answer_characters": answer_characters,
                "turn_count": turn_count,
                "tool_call_count": tool_call_count,
                "sources_found": sources_found,
                "sources_used": sources_used,
            },
        )
        self._finished = True

    def fail(self, *, stage: str) -> None:
        _safe_update(
            self._observation,
            output={"status": "failed", "stage": stage},
            level="ERROR",
            status_message=stage,
        )
        self._finished = True

    def cancel(self) -> None:
        _safe_update(
            self._observation,
            output={"status": "cancelled"},
            level="WARNING",
            status_message="request_cancelled",
        )
        self._finished = True


@dataclass(slots=True)
class CapabilityTrace:
    """Controlled updates for one named knowledge-agent LLM capability."""

    _observation: _Observation
    _metadata: dict[str, Any]
    _first_token_recorded: bool = False

    def mark_first_token(self) -> None:
        if self._first_token_recorded:
            return
        _safe_update(
            self._observation,
            completion_start_time=datetime.now(UTC),
        )
        self._first_token_recorded = True

    def complete(
        self,
        *,
        response: LLMResponse | ModelTurn,
        output: Any,
        duration_ms: int,
    ) -> None:
        usage = response.usage
        metadata = {
            **self._metadata,
            "finish_reason": response.finish_reason,
            "llm_latency_ms": duration_ms,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "cached_prompt_tokens": usage.get("cached_prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }
        _safe_update(
            self._observation,
            model=response.model,
            usage_details=_usage_details(usage),
            output=output,
            metadata=metadata,
        )

    def fail(
        self,
        *,
        category: str,
        duration_ms: int,
        response: LLMResponse | ModelTurn | None = None,
        output: Any = None,
    ) -> None:
        update: dict[str, Any] = {
            "metadata": {
                **self._metadata,
                "llm_latency_ms": duration_ms,
                "outcome": category,
            },
            "level": "ERROR",
            "status_message": category,
        }
        if response is not None:
            usage = response.usage
            update.update(
                model=response.model,
                usage_details=_usage_details(usage),
                output=output,
                metadata={
                    **update["metadata"],
                    "finish_reason": response.finish_reason,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "cached_prompt_tokens": usage.get("cached_prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                },
            )
        _safe_update(self._observation, **update)


@dataclass(slots=True)
class ToolExecutionTrace:
    """Controlled updates for one non-retrieval agent tool call."""

    _observation: _Observation

    def complete(self, *, result: ToolResult) -> None:
        update: dict[str, Any] = {
            "output": {
                "content": result.content,
                "error": result.error,
                "metadata": result.metadata,
                "evidence_ids": [evidence.id for evidence in result.evidence],
            }
        }
        if result.error:
            update.update(level="ERROR", status_message=result.error)
        _safe_update(self._observation, **update)


@dataclass(slots=True)
class RetrievalTrace:
    """Controlled updates for one enterprise knowledge lookup."""

    _observation: _Observation
    _metadata: dict[str, Any]

    def complete(
        self,
        *,
        outcome: str,
        result_count: int,
        source_types: Sequence[str] = (),
        results: Sequence[Evidence] = (),
        duration_ms: int = 0,
    ) -> None:
        _safe_update(
            self._observation,
            output=[_evidence_result(result) for result in results],
            metadata={
                **self._metadata,
                "outcome": outcome,
                "result_count": result_count,
                "source_types": sorted(set(source_types)),
                "retrieval_latency_ms": duration_ms,
            },
        )

    def fail(self, *, category: str, duration_ms: int = 0) -> None:
        _safe_update(
            self._observation,
            output={"outcome": category, "result_count": 0},
            metadata={
                **self._metadata,
                "outcome": category,
                "result_count": 0,
                "retrieval_latency_ms": duration_ms,
            },
            level="ERROR",
            status_message=category,
        )


class LangfuseTracing:
    """Small adapter around Langfuse v4 with explicit chat payloads."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @contextmanager
    def agent_run(
        self,
        *,
        user_message: str,
        ctx: AgentContext,
    ) -> Iterator[AgentRunTrace]:
        from langfuse import propagate_attributes

        trace_context = _trace_context(ctx.request_id)
        trace_name = _trace_name(ctx.request_id)
        with (
            self._client.start_as_current_observation(
                as_type="agent",
                name="respond-to-chat",
                input=user_message,
                metadata={
                    "request_id": ctx.request_id,
                    "conversation_id": ctx.conversation_id,
                    "history_message_count": len(ctx.history),
                },
                trace_context=trace_context,
            ) as observation,
            propagate_attributes(
                user_id=_pseudonymous_user_id(ctx.user_id),
                session_id=ctx.conversation_id,
                tags=["chat", "enterprise-knowledge"],
                trace_name=trace_name,
            ),
        ):
            trace = AgentRunTrace(observation)
            try:
                yield trace
            except (GeneratorExit, asyncio.CancelledError):
                if not trace._finished:
                    trace.cancel()
                raise
            except BaseException:
                if not trace._finished:
                    trace.fail(stage="unhandled_exception")
                raise
            finally:
                if not trace._finished:
                    trace.cancel()

    def retrieval(
        self,
        *,
        query: str,
        result_limit: int,
        ctx: AgentContext,
    ) -> AbstractContextManager[RetrievalTrace]:
        return _retrieval_context(
            self._client,
            query=query,
            result_limit=result_limit,
            ctx=ctx,
        )

    def capability(
        self,
        *,
        capability: str,
        prompt: str,
        ctx: AgentContext,
        step: int,
        retrieval_round: int,
        retrieval_query_count: int,
    ) -> AbstractContextManager[CapabilityTrace]:
        return _capability_context(
            self._client,
            capability=capability,
            prompt=prompt,
            ctx=ctx,
            step=step,
            retrieval_round=retrieval_round,
            retrieval_query_count=retrieval_query_count,
        )

    def tool_execution(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
    ) -> AbstractContextManager[ToolExecutionTrace]:
        return _tool_execution_context(
            self._client,
            name=name,
            arguments=arguments,
        )

    def flush(self) -> None:
        self._client.flush()


def create_langfuse_tracing() -> LangfuseTracing | None:
    """Create tracing only when both project keys are configured."""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key and not secret_key:
        return None
    if not public_key or not secret_key:
        log.warning("langfuse_tracing_disabled reason=incomplete_credentials")
        return None

    # Import after the process environment is loaded so the SDK sees the
    # correct project keys and base URL.
    from langfuse import get_client

    return LangfuseTracing(get_client())


@contextmanager
def _capability_context(
    client: Any,
    *,
    capability: str,
    prompt: str,
    ctx: AgentContext,
    step: int,
    retrieval_round: int,
    retrieval_query_count: int,
) -> Iterator[CapabilityTrace]:
    metadata = {
        "request_id": ctx.request_id,
        "conversation_id": ctx.conversation_id,
        "step": step,
        "capability": capability,
        "retrieval_round": retrieval_round,
        "retrieval_query_count": retrieval_query_count,
    }
    with client.start_as_current_observation(
        as_type="generation",
        name=capability,
        input=[{"role": "user", "content": prompt}],
        metadata=metadata,
    ) as observation:
        yield CapabilityTrace(observation, metadata)


@contextmanager
def _tool_execution_context(
    client: Any,
    *,
    name: str,
    arguments: Mapping[str, Any],
) -> Iterator[ToolExecutionTrace]:
    with client.start_as_current_observation(
        as_type="tool",
        name=name,
        input=dict(arguments),
    ) as observation:
        yield ToolExecutionTrace(observation)


@contextmanager
def _retrieval_context(
    client: Any,
    *,
    query: str,
    result_limit: int,
    ctx: AgentContext,
) -> Iterator[RetrievalTrace]:
    metadata = {
        "request_id": ctx.request_id,
        "conversation_id": ctx.conversation_id,
        "step": ctx.trace_step,
        "capability": "retrieval",
        "retrieval_round": ctx.retrieval_round,
        "retrieval_query_count": ctx.retrieval_query_count,
        "result_limit": result_limit,
    }
    with client.start_as_current_observation(
        as_type="retriever",
        name="retrieve-knowledge",
        input={"query": query, "result_limit": result_limit},
        metadata=metadata,
    ) as observation:
        yield RetrievalTrace(observation, metadata)


def _usage_details(usage: Mapping[str, int]) -> dict[str, int] | None:
    details: dict[str, int] = {}
    prompt_tokens = usage.get("prompt_tokens")
    cached_prompt_tokens = usage.get("cached_prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    if prompt_tokens is not None:
        details["input"] = max(0, prompt_tokens - cached_prompt_tokens)
    if cached_prompt_tokens:
        details["input_cached_tokens"] = cached_prompt_tokens
    if completion_tokens is not None:
        details["output"] = completion_tokens
    if total_tokens is not None:
        details["total"] = total_tokens
    return details or None


def _safe_update(observation: _Observation, **kwargs: Any) -> None:
    try:
        observation.update(**kwargs)
    except Exception as error:  # noqa: BLE001 - tracing must not break chat requests
        log.warning(
            "langfuse_trace_update_failed error_category=%s",
            type(error).__name__,
        )


def _evidence_result(evidence: Evidence) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "document_id": evidence.document_id,
        "title": evidence.title,
        "content": evidence.content,
        "page": evidence.page,
        "section": evidence.section,
        "uri": evidence.uri,
        "source": evidence.source,
        "relevance_score": evidence.relevance_score,
    }


def _pseudonymous_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]


def _trace_context(request_id: str | None) -> dict[str, str] | None:
    if not request_id or len(request_id) != 32:
        return None
    try:
        int(request_id, 16)
    except ValueError:
        return None
    return {"trace_id": request_id.lower()}


def _trace_name(request_id: str | None) -> str:
    trace_context = _trace_context(request_id)
    if trace_context is None:
        return "chat-request"
    return f"chat-{trace_context['trace_id'][:8]}"


__all__ = [
    "AgentRunTrace",
    "CapabilityTrace",
    "LangfuseTracing",
    "RetrievalTrace",
    "ToolExecutionTrace",
    "create_langfuse_tracing",
]
