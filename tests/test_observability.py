from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import (
    AgentContext,
    Evidence,
    ModelTurn,
    ToolCall,
    ToolResult,
)
from bothesis.agent.transports.base import LLMResponse
from bothesis.observability import LangfuseTracing, _trace_name


class RecordingObservation:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class RecordingClient:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.observations: list[RecordingObservation] = []
        self.flush_count = 0

    @contextmanager
    def start_as_current_observation(
        self, **kwargs: Any
    ) -> Iterator[RecordingObservation]:
        observation = RecordingObservation()
        self.starts.append(kwargs)
        self.observations.append(observation)
        yield observation

    def flush(self) -> None:
        self.flush_count += 1


def test_agent_trace_captures_content_with_safe_correlations() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)
    context = AgentContext(
        user_id="employee@example.com",
        tenant_id="tenant-secret",
        roles=["admin"],
        request_id="0123456789abcdef0123456789abcdef",
        conversation_id="conversation-1",
    )

    with tracing.agent_run(
        user_message="private enterprise question", ctx=context
    ) as trace:
        trace.complete(
            answer="Grounded enterprise answer",
            answer_characters=120,
            turn_count=2,
            tool_call_count=1,
            sources_found=5,
            sources_used=2,
        )

    serialized = json.dumps(
        {"starts": client.starts, "updates": client.observations[0].updates},
        default=str,
    )
    assert "private enterprise question" in serialized
    assert "Grounded enterprise answer" in serialized
    assert "employee@example.com" not in serialized
    assert "tenant-secret" not in serialized
    assert client.starts[0]["as_type"] == "agent"
    assert client.starts[0]["trace_context"] == {
        "trace_id": "0123456789abcdef0123456789abcdef"
    }
    assert client.starts[0]["input"] == "private enterprise question"
    assert client.starts[0]["metadata"]["conversation_id"] == "conversation-1"
    assert client.observations[0].updates[-1]["output"] == "Grounded enterprise answer"


def test_trace_name_uses_a_short_valid_request_id() -> None:
    assert _trace_name("0123456789ABCDEF0123456789ABCDEF") == "chat-01234567"
    assert _trace_name("not-a-valid-trace-id") == "chat-request"
    assert _trace_name(None) == "chat-request"


def test_capability_trace_captures_model_usage_cache_and_execution_metadata() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)
    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=[],
        request_id="request-1",
        conversation_id="conversation-1",
    )

    with tracing.capability(
        capability="query_rewrite",
        messages=[
            {"role": "system", "content": "BoThesis base prompt"},
            {
                "role": "user",
                "content": "<task>Rewrite</task><input>sensitive prompt</input>",
            },
        ],
        ctx=context,
        step=1,
        retrieval_round=0,
        retrieval_query_count=0,
    ) as trace:
        trace.mark_first_token()
        trace.mark_first_token()
        trace.complete(
            response=LLMResponse(
                id="response-1",
                model="openai/gpt-5.4-mini",
                content='{"query":"leave policy"}',
                usage={
                    "prompt_tokens": 20,
                    "cached_prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 28,
                },
                finish_reason="tool_calls",
            ),
            output={"query": "leave policy"},
            duration_ms=125,
        )

    serialized = json.dumps(
        {"starts": client.starts, "updates": client.observations[0].updates},
        default=str,
    )
    assert "sensitive prompt" in serialized
    assert "leave policy" in serialized
    assert client.starts[0]["as_type"] == "generation"
    assert client.starts[0]["name"] == "query_rewrite"
    assert client.starts[0]["input"][0] == {
        "role": "system",
        "content": "BoThesis base prompt",
    }
    assert (
        sum(
            "completion_start_time" in update
            for update in client.observations[0].updates
        )
        == 1
    )
    update = client.observations[0].updates[-1]
    assert update["usage_details"] == {
        "input": 8,
        "input_cached_tokens": 12,
        "output": 8,
        "total": 28,
    }
    assert update["metadata"] == {
        "request_id": "request-1",
        "conversation_id": "conversation-1",
        "step": 1,
        "capability": "query_rewrite",
        "retrieval_round": 0,
        "retrieval_query_count": 0,
        "finish_reason": "tool_calls",
        "llm_latency_ms": 125,
        "prompt_tokens": 20,
        "cached_prompt_tokens": 12,
        "completion_tokens": 8,
    }


def test_capability_trace_records_invalid_response_failure() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)
    context = AgentContext(user_id="u", tenant_id="t", roles=[])

    with tracing.capability(
        capability="retrieval_evaluate",
        messages=[{"role": "user", "content": "prompt"}],
        ctx=context,
        step=4,
        retrieval_round=1,
        retrieval_query_count=2,
    ) as trace:
        trace.fail(
            category="invalid_response",
            duration_ms=20,
            response=LLMResponse(
                id="response-2",
                model="openai/gpt-5.4-mini",
                content="truncated-json",
                finish_reason="length",
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            ),
            output="truncated-json",
        )

    update = client.observations[0].updates[-1]
    assert update["level"] == "ERROR"
    assert update["output"] == "truncated-json"
    assert update["model"] == "openai/gpt-5.4-mini"
    assert update["metadata"]["outcome"] == "invalid_response"
    assert update["metadata"]["retrieval_round"] == 1
    assert update["metadata"]["completion_tokens"] == 50


def test_model_turn_trace_is_named_from_the_returned_tool_calls() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)
    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=[],
        request_id="request-1",
        conversation_id="conversation-1",
    )

    with tracing.model_turn(
        messages=[{"role": "user", "content": "What is our leave policy?"}],
        ctx=context,
        turn=0,
        tool_round=0,
    ) as trace:
        trace.complete(
            turn=ModelTurn(
                text="",
                tool_calls=[
                    ToolCall(
                        call_id="search-1",
                        name="knowledge_search",
                        arguments={"query": "annual leave policy"},
                    )
                ],
                finish_reason="tool_calls",
                model="openai/gpt-5.4-mini",
                usage={"prompt_tokens": 20, "completion_tokens": 4},
            ),
            duration_ms=80,
        )

    assert client.starts[0]["name"] == "agent-model-turn"
    update = client.observations[0].updates[-1]
    assert update["name"] == "decide-next-step"
    assert update["output"]["tool_calls"][0]["arguments"] == {
        "query": "annual leave policy"
    }
    assert update["metadata"]["generation_kind"] == "next_step"
    assert update["metadata"]["selected_tools"] == ["knowledge_search"]
    assert update["metadata"]["tool_call_count"] == 1


def test_model_turn_trace_names_a_text_response_as_final() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)
    context = AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[])

    with tracing.model_turn(
        messages=[{"role": "user", "content": "Hello"}],
        ctx=context,
        turn=0,
        tool_round=0,
    ) as trace:
        trace.complete(
            turn=ModelTurn(
                text="Hello!",
                tool_calls=[],
                finish_reason="stop",
                model="openai/gpt-5.4-mini",
            ),
            duration_ms=30,
        )

    update = client.observations[0].updates[-1]
    assert update["name"] == "generate-final-response"
    assert update["output"] == "Hello!"
    assert update["metadata"]["generation_kind"] == "final_response"


def test_tool_execution_trace_uses_the_tool_name() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)

    with tracing.tool_execution(
        name="calculate_metric",
        arguments={"metric": "net_interest_margin"},
    ) as trace:
        trace.complete(
            result=ToolResult(
                call_id="call-1",
                content="3.2%",
                metadata={"outcome": "success"},
            )
        )

    assert client.starts[0]["as_type"] == "tool"
    assert client.starts[0]["name"] == "calculate_metric"
    assert client.observations[0].updates[-1]["output"]["content"] == "3.2%"


def test_retrieval_trace_captures_query_and_normalized_results() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)

    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=[],
        request_id="request-1",
        conversation_id="conversation-1",
        trace_step=3,
        retrieval_round=1,
        retrieval_query_count=2,
    )
    with tracing.retrieval(
        query="confidential policy terms",
        result_limit=5,
        ctx=context,
    ) as trace:
        trace.complete(
            outcome="success",
            result_count=1,
            source_types=["confluence"],
            results=[
                Evidence(
                    id="chunk-1",
                    document_id="doc-1",
                    title="Leave policy",
                    content="Employees receive 20 days of annual leave.",
                    source="confluence",
                    relevance_score=0.91,
                )
            ],
            duration_ms=75,
        )

    serialized = json.dumps(
        {"starts": client.starts, "updates": client.observations[0].updates}
    )
    assert "confidential policy terms" in serialized
    assert "Employees receive 20 days of annual leave." in serialized
    assert client.starts[0]["as_type"] == "retriever"
    assert client.starts[0]["name"] == "retrieve-knowledge"
    assert client.observations[0].updates[-1]["output"][0]["id"] == "chunk-1"
    metadata = client.observations[0].updates[-1]["metadata"]
    assert metadata["request_id"] == "request-1"
    assert metadata["retrieval_latency_ms"] == 75
    assert metadata["retrieval_query_count"] == 2
