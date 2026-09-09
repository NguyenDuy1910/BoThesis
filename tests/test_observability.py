from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.protocol import InputText, MessageItem, Prompt
from bothesis.observability import LangfuseTracer, NoopTracer, TraceSerializer


class RecordingObservation:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class RecordingClient:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.observations: list[RecordingObservation] = []

    @contextmanager
    def start_as_current_observation(
        self, **kwargs: Any
    ) -> Iterator[RecordingObservation]:
        observation = RecordingObservation()
        self.starts.append(kwargs)
        self.observations.append(observation)
        yield observation

    def flush(self) -> None:
        return None


def test_serializer_redacts_secrets_and_omits_raw_content() -> None:
    serialized = TraceSerializer.value(
        {
            "authorization": "Bearer sk-super-secret-value",
            "content": "confidential document body",
            "attachment": b"binary-data",
            "label": "normal",
        }
    )

    assert serialized == {
        "authorization": "[redacted]",
        "content": {"omitted": True, "character_count": len("confidential document body")},
        "attachment": {"omitted": True, "byte_count": len(b"binary-data")},
        "label": "normal",
    }


def test_noop_tracer_never_changes_runtime_control_flow() -> None:
    with NoopTracer().generation("model.sample", model="test") as span:
        span.mark_first_token()
        span.set_attribute("step", 1)
        span.set_output({"answer": "ok"})


def test_agent_turn_uses_domain_identifiers_and_pseudonymous_user() -> None:
    client = RecordingClient()
    tracer = LangfuseTracer(client)

    with tracer.span(
        "agent.turn",
        attributes={
            "conversation_id": "conversation-1",
            "turn_id": "turn-1",
            "request_id": "0123456789abcdef0123456789abcdef",
            "user_id": "pseudonymous-user",
        },
        input=TraceSerializer.turn_input(
            user_input="What is the leave policy?",
            model="openai/gpt-5",
            available_tool_count=4,
        ),
    ) as span:
        span.set_output(
            TraceSerializer.turn_output(
                status="completed", step_count=2, tool_call_count=1, final_answer="Answer"
            )
        )

    assert client.starts[0]["as_type"] == "agent"
    assert client.starts[0]["trace_context"] == {
        "trace_id": "0123456789abcdef0123456789abcdef"
    }
    assert client.starts[0]["metadata"]["conversation_id"] == "conversation-1"
    assert client.observations[0].updates[-1]["output"]["final_answer_length"] == 6


def test_generation_records_model_payload_when_marked_detailed() -> None:
    client = RecordingClient()
    tracer = LangfuseTracer(client)

    with tracer.generation(
        "model.sample",
        model="openai/gpt-5",
        attributes={"step": 2},
        input=TraceSerializer.full(
            {"normalized_request": {"instructions": "Follow the policy.", "input": []}}
        ),
    ) as span:
        span.mark_first_token()
        span.set_output(
            {"finish_reason": "tool_calls", "tool_calls": ["knowledge_search"], "output_text_length": 0}
        )

    assert client.starts[0] == {
        "as_type": "generation",
        "name": "model.sample",
        "input": {"normalized_request": {"instructions": "Follow the policy.", "input": []}},
        "metadata": {"step": 2},
        "model": "openai/gpt-5",
    }
    assert client.observations[0].updates[-1]["output"]["tool_calls"] == [
        "knowledge_search"
    ]


def test_model_context_trace_exposes_the_full_normalized_request() -> None:
    prompt = Prompt(
        input=(MessageItem(role="user", content=(InputText(text="sensitive request"),)),),
        tools=(),
    )

    summary = TraceSerializer.model_input(
        prompt,
        step_context=type(
            "Step",
            (),
            {
                "turn_id": "turn-1",
                "step_index": 1,
                "settings": None,
                "instructions": "Follow the policy.",
                "input_items": prompt.input,
                "tools": (),
            },
        )(),
    )

    assert summary["normalized_request"]["input"][0]["content"][0]["text"] == "sensitive request"
    assert summary["context_metrics"]["message_count"] == 1
    assert summary["step_context"]["turn_id"] == "turn-1"


def test_tool_trace_includes_safe_arguments_and_structured_results() -> None:
    client = RecordingClient()
    tracer = LangfuseTracer(client)

    with tracer.span(
        "tool.execute: read_resource",
        attributes={"tool_name": "read_resource", "tool_call_id": "call-1"},
        input=TraceSerializer.full(TraceSerializer.tool_input(
            tool_name="read_resource", arguments={"resource_id": "document-1"}
        )),
    ) as span:
        span.set_output(
            {
                "outcome": "success",
                "result_character_count": 4_000,
                "evidence_count": 2,
                "has_error": False,
            }
        )

    serialized = json.dumps(
        {"start": client.starts[0], "updates": client.observations[0].updates}
    )
    assert "document-1" in serialized
    assert client.starts[0]["as_type"] == "tool"
    assert client.starts[0]["input"] == {
        "tool_name": "read_resource",
        "arguments": {"resource_id": "document-1"},
    }
    assert client.observations[0].updates[-1]["output"]["result_character_count"] == 4_000


def test_detailed_payload_keeps_model_text_but_redacts_credentials_and_signed_urls() -> None:
    client = RecordingClient()
    tracer = LangfuseTracer(client)

    with tracer.generation(
        "model.sample",
        model="openai/gpt-5",
        input=TraceSerializer.full(
            {
                "instructions": "Use the attached policy.",
                "authorization": "Bearer sk-super-secret-value",
                "image_url": "https://storage.example/signed?token=secret",
                "content": "The exact model-visible context.",
            }
        ),
    ):
        pass

    payload = client.starts[0]["input"]
    assert payload["content"] == "The exact model-visible context."
    assert payload["authorization"] == "[redacted]"
    assert payload["image_url"] == {"omitted": True, "character_count": 43}


def test_span_records_a_safe_error_automatically() -> None:
    client = RecordingClient()
    tracer = LangfuseTracer(client)

    with pytest.raises(ValueError, match="bad secret"):
        with tracer.span("tool.execute"):
            raise ValueError("bad secret")

    update = client.observations[0].updates[-1]
    assert update["level"] == "ERROR"
    assert update["output"]["exception"]["type"] == "ValueError"
