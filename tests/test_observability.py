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
    assert client.observations[0].updates[-1]["output"] == "Grounded enterprise answer"


def test_trace_name_uses_a_short_valid_request_id() -> None:
    assert _trace_name("0123456789ABCDEF0123456789ABCDEF") == "chat-01234567"
    assert _trace_name("not-a-valid-trace-id") == "chat-request"
    assert _trace_name(None) == "chat-request"


def test_generation_trace_captures_messages_response_and_usage() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)

    with tracing.generation(
        turn=1,
        messages=[{"role": "user", "content": "sensitive prompt"}],
        tool_count=1,
    ) as trace:
        trace.mark_first_token()
        trace.mark_first_token()
        trace.complete(
            turn=ModelTurn(
                text="I will search the knowledge base.",
                tool_calls=[
                    ToolCall(
                        call_id="call-1",
                        name="knowledge_search",
                        arguments={"query": "leave policy"},
                    )
                ],
                model="openai/gpt-5.4-mini",
                usage={
                    "prompt_tokens": 20,
                    "completion_tokens": 8,
                    "total_tokens": 28,
                },
                finish_reason="tool_calls",
            )
        )

    serialized = json.dumps(
        {"starts": client.starts, "updates": client.observations[0].updates},
        default=str,
    )
    assert "sensitive prompt" in serialized
    assert "I will search the knowledge base." in serialized
    assert "leave policy" in serialized
    assert client.starts[0]["as_type"] == "generation"
    assert client.starts[0]["name"] == "agent-model-turn"
    assert (
        sum(
            "completion_start_time" in update
            for update in client.observations[0].updates
        )
        == 1
    )
    assert client.observations[0].updates[-1]["usage_details"] == {
        "input_tokens": 20,
        "output_tokens": 8,
        "total_tokens": 28,
    }
    assert client.observations[0].updates[-1]["name"] == "decide-next-step"
    assert client.observations[0].updates[-1]["metadata"] == {
        "turn": 1,
        "generation_kind": "next_step",
        "finish_reason": "tool_calls",
        "tool_call_count": 1,
        "selected_tools": ["knowledge_search"],
    }


def test_generation_trace_names_a_final_response() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)

    with tracing.generation(
        turn=2,
        messages=[{"role": "user", "content": "Summarize the evidence"}],
        tool_count=1,
    ) as trace:
        trace.complete(
            turn=ModelTurn(
                text="Final grounded answer.",
                tool_calls=[],
                model="openai/gpt-5.4-mini",
                usage={},
                finish_reason="stop",
            )
        )

    update = client.observations[0].updates[-1]
    assert update["name"] == "generate-final-response"
    assert update["metadata"]["generation_kind"] == "final_response"
    assert update["metadata"]["selected_tools"] == []


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

    with tracing.retrieval(query="confidential policy terms", result_limit=5) as trace:
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
        )

    serialized = json.dumps(
        {"starts": client.starts, "updates": client.observations[0].updates}
    )
    assert "confidential policy terms" in serialized
    assert "Employees receive 20 days of annual leave." in serialized
    assert client.starts[0]["as_type"] == "retriever"
    assert client.observations[0].updates[-1]["output"][0]["id"] == "chunk-1"
