from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import AgentContext
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


def test_agent_trace_uses_safe_correlations_without_content() -> None:
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
    assert "private enterprise question" not in serialized
    assert "employee@example.com" not in serialized
    assert "tenant-secret" not in serialized
    assert client.starts[0]["as_type"] == "agent"
    assert client.starts[0]["trace_context"] == {
        "trace_id": "0123456789abcdef0123456789abcdef"
    }
    assert client.starts[0]["input"] == {
        "message_characters": 27,
        "history_message_count": 0,
    }
    assert client.observations[0].updates[-1]["output"]["status"] == "completed"


def test_trace_name_uses_a_short_valid_request_id() -> None:
    assert _trace_name("0123456789ABCDEF0123456789ABCDEF") == "chat-01234567"
    assert _trace_name("not-a-valid-trace-id") == "chat-request"
    assert _trace_name(None) == "chat-request"


def test_generation_trace_normalizes_openrouter_usage() -> None:
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
            model="openai/gpt-5.4-mini",
            usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            finish_reason="stop",
            text_characters=42,
            tool_call_count=0,
        )

    serialized = json.dumps(
        {"starts": client.starts, "updates": client.observations[0].updates},
        default=str,
    )
    assert "sensitive prompt" not in serialized
    assert client.starts[0]["as_type"] == "generation"
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


def test_retrieval_trace_excludes_query_and_source_content() -> None:
    client = RecordingClient()
    tracing = LangfuseTracing(client)

    with tracing.retrieval(query="confidential policy terms", result_limit=5) as trace:
        trace.complete(
            outcome="success",
            result_count=2,
            source_types=["confluence", "confluence"],
        )

    serialized = json.dumps(
        {"starts": client.starts, "updates": client.observations[0].updates}
    )
    assert "confidential policy terms" not in serialized
    assert client.starts[0]["as_type"] == "retriever"
    assert client.observations[0].updates[-1]["output"] == {
        "outcome": "success",
        "result_count": 2,
        "source_types": ["confluence"],
    }
