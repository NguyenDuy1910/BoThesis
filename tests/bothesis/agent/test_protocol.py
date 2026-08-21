"""Contract tests for the OpenResponses protocol models.

The protocol is a mirror of the specification (https://www.openresponses.org,
version 2026-04-24), so these tests assert specification parity: the item union,
the content families, the item and response state machines, the assistant
``phase`` field, and the complete streaming event union.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from bothesis.agent.protocol import (
    DOCUMENT_CITATION_TYPE,
    AllowedTools,
    CompactionItem,
    ExtensionItem,
    ExtensionTool,
    FunctionCallItem,
    FunctionCallOutputItem,
    FunctionTool,
    FunctionToolChoice,
    IncompleteDetails,
    InputFile,
    InputImage,
    InputText,
    InputTokensDetails,
    ItemAdapter,
    MessageItem,
    OutputText,
    ReasoningItem,
    ReasoningText,
    Refusal,
    Response,
    ResponseError,
    ResponseRequest,
    ResponseStreamEventAdapter,
    ResponseUsage,
    SummaryText,
    ToolAdapter,
)
from bothesis.agent.protocol.content import ContentPart
from bothesis.agent.protocol.items import ItemStatus
from bothesis.agent.protocol.responses import ResponseStatus
from pydantic import TypeAdapter

_CONTENT_ADAPTER: TypeAdapter[ContentPart] = TypeAdapter(ContentPart)

# Every event the specification lists for ``text/event-stream`` responses.
SPECIFIED_EVENT_TYPES = frozenset(
    {
        "response.created",
        "response.queued",
        "response.in_progress",
        "response.completed",
        "response.failed",
        "response.incomplete",
        "response.output_item.added",
        "response.output_item.done",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_part.done",
        "response.content_part.added",
        "response.content_part.done",
        "response.output_text.delta",
        "response.output_text.done",
        "response.output_text.annotation.added",
        "response.refusal.delta",
        "response.refusal.done",
        "response.reasoning.delta",
        "response.reasoning.done",
        "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.done",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "error",
    }
)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
            MessageItem,
        ),
        ({"type": "reasoning", "summary": []}, ReasoningItem),
        (
            {"type": "function_call", "call_id": "call-1", "name": "search", "arguments": "{}"},
            FunctionCallItem,
        ),
        (
            {"type": "function_call_output", "call_id": "call-1", "output": "done"},
            FunctionCallOutputItem,
        ),
        ({"type": "compaction", "encrypted_content": "opaque"}, CompactionItem),
        ({"type": "web_search_call", "status": "searching"}, ExtensionItem),
    ],
)
def test_item_union_covers_every_specified_item_type(
    payload: dict, expected: type
) -> None:
    assert isinstance(ItemAdapter.validate_python(payload), expected)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"type": "input_text", "text": "hi"}, InputText),
        ({"type": "input_image", "image_url": "https://x/y.png"}, InputImage),
        ({"type": "input_file", "file_id": "file-1"}, InputFile),
        ({"type": "output_text", "text": "answer"}, OutputText),
        ({"type": "refusal", "refusal": "no"}, Refusal),
        ({"type": "reasoning_text", "text": "thinking"}, ReasoningText),
        ({"type": "summary_text", "text": "plan"}, SummaryText),
    ],
)
def test_content_union_covers_every_specified_part(
    payload: dict, expected: type
) -> None:
    assert isinstance(_CONTENT_ADAPTER.validate_python(payload), expected)


def test_item_status_is_the_specified_state_machine() -> None:
    assert set(ItemStatus.__args__) == {"in_progress", "completed", "incomplete"}


def test_response_status_covers_the_specified_lifecycle() -> None:
    assert {"queued", "in_progress", "completed", "incomplete", "failed"} <= set(
        ResponseStatus.__args__
    )


def test_stream_event_union_is_exactly_the_specified_event_set() -> None:
    schema = ResponseStreamEventAdapter.core_schema
    while "choices" not in schema:
        schema = schema["schema"]

    assert set(schema["choices"]) == SPECIFIED_EVENT_TYPES


def test_assistant_message_carries_the_phase_field() -> None:
    commentary = MessageItem(
        role="assistant",
        phase="commentary",
        content=(OutputText(text="Let me look that up."),),
    )
    answer = MessageItem(
        role="assistant",
        phase="final_answer",
        content=(OutputText(text="42"),),
    )
    response = Response(status="completed", output=(commentary, answer))

    assert response.commentary_text == "Let me look that up."
    assert response.final_answer_text == "42"
    assert response.output_text == "Let me look that up.42"


def test_phase_is_rejected_when_it_is_not_a_specified_value() -> None:
    with pytest.raises(ValidationError):
        MessageItem(role="assistant", phase="draft", content=())


def test_final_answer_falls_back_when_no_message_declares_a_phase() -> None:
    """A provider that predates ``phase`` still yields a usable answer."""

    response = Response(
        status="completed",
        output=(MessageItem(role="assistant", content=(OutputText(text="42"),)),),
    )

    assert response.final_answer_text == "42"


def test_final_answer_is_empty_while_the_response_is_only_commentary() -> None:
    response = Response(
        status="completed",
        output=(
            MessageItem(
                role="assistant",
                phase="commentary",
                content=(OutputText(text="Searching."),),
            ),
            FunctionCallItem(call_id="call-1", name="search", arguments="{}"),
        ),
    )

    assert response.final_answer_text == ""
    assert response.function_calls[0].name == "search"


def test_reasoning_item_exposes_content_and_summary_separately() -> None:
    item = ReasoningItem(
        content=(ReasoningText(text="raw thought"),),
        summary=(SummaryText(text="plan"),),
        encrypted_content="opaque",
    )

    assert item.reasoning_text == "raw thought"
    assert item.summary_text == "plan"
    # ``encrypted_content`` is the specified continuation blob, so no
    # BoThesis-specific field is needed to replay a reasoning item.
    assert item.encrypted_content == "opaque"


def test_function_call_output_defaults_to_the_completed_status() -> None:
    assert FunctionCallOutputItem(call_id="call-1", output="done").status == "completed"


def test_function_call_arguments_decode_to_a_json_object() -> None:
    call = FunctionCallItem(
        call_id="call-1", name="search", arguments='{"queries": ["policy"]}'
    )

    assert call.parsed_arguments() == {"queries": ["policy"]}
    assert FunctionCallItem(call_id="c", name="n", arguments=" ").parsed_arguments() == {}


@pytest.mark.parametrize("arguments", ["[1, 2]", "not json", '"text"'])
def test_function_call_arguments_reject_non_objects(arguments: str) -> None:
    call = FunctionCallItem(call_id="call-1", name="search", arguments=arguments)

    with pytest.raises(ValueError):
        call.parsed_arguments()


def test_function_call_identity_is_required() -> None:
    with pytest.raises(ValidationError):
        FunctionCallItem(call_id="", name="search")
    with pytest.raises(ValidationError):
        FunctionCallItem(call_id="call-1", name="")


def test_tool_union_separates_function_and_provider_tools() -> None:
    function_tool = ToolAdapter.validate_python(
        {"type": "function", "name": "search", "parameters": {"type": "object"}}
    )
    hosted = ToolAdapter.validate_python({"type": "web_search_preview", "region": "eu"})

    assert isinstance(function_tool, FunctionTool)
    assert isinstance(hosted, ExtensionTool)
    assert hosted.model_dump()["region"] == "eu"


@pytest.mark.parametrize("mode", ["none", "auto", "required"])
def test_tool_choice_accepts_the_plain_modes(mode: str) -> None:
    assert ResponseRequest(input=(), tool_choice=mode).tool_choice == mode


def test_tool_choice_accepts_a_named_function_and_allowed_tools() -> None:
    named = ResponseRequest(
        input=(), tool_choice=FunctionToolChoice(name="search")
    ).tool_choice
    allowed = ResponseRequest(
        input=(),
        tool_choice=AllowedTools(mode="required", tools=({"name": "search"},)),
    ).tool_choice

    assert isinstance(named, FunctionToolChoice)
    assert isinstance(allowed, AllowedTools)
    assert allowed.tools[0].name == "search"


def test_allowed_tools_requires_at_least_one_tool() -> None:
    with pytest.raises(ValidationError):
        AllowedTools(tools=())


def test_request_round_trips_through_json() -> None:
    request = ResponseRequest(
        input=(
            MessageItem(role="user", content=(InputText(text="hello"),)),
            ReasoningItem(summary=(SummaryText(text="plan"),), encrypted_content="x"),
            FunctionCallItem(call_id="call-1", name="search", arguments='{"q":"a"}'),
            FunctionCallOutputItem(call_id="call-1", output="found"),
        ),
        model="test-model",
        instructions="be brief",
        tools=(FunctionTool(name="search", parameters={"type": "object"}),),
        tool_choice="auto",
        previous_response_id="resp_1",
        provider_options={"reasoning": {"effort": "low"}},
    )

    restored = ResponseRequest.model_validate_json(request.model_dump_json())

    assert restored == request


def test_response_round_trips_through_json() -> None:
    response = Response(
        id="resp_1",
        status="completed",
        created_at=1,
        completed_at=2,
        model="gpt-test",
        previous_response_id="resp_0",
        output=(
            ReasoningItem(
                id="rs_1",
                status="completed",
                content=(ReasoningText(text="thought"),),
                summary=(SummaryText(text="plan"),),
            ),
            MessageItem(
                id="msg_1",
                role="assistant",
                status="completed",
                phase="final_answer",
                content=(
                    OutputText(
                        text="grounded",
                        annotations=(
                            {
                                "type": DOCUMENT_CITATION_TYPE,
                                "start_index": 0,
                                "end_index": 8,
                                "citation": {"id": "ev-1"},
                            },
                        ),
                    ),
                ),
            ),
        ),
        usage=ResponseUsage(
            input_tokens=5,
            input_tokens_details=InputTokensDetails(cached_tokens=2),
            output_tokens=3,
            total_tokens=8,
        ),
        incomplete_details=None,
    )

    restored = Response.model_validate_json(response.model_dump_json())

    assert restored == response
    assert restored.output_annotations[0]["citation"]["id"] == "ev-1"


def test_document_citation_uses_the_required_implementer_slug() -> None:
    """The specification requires implementer types to be slug-prefixed."""

    assert DOCUMENT_CITATION_TYPE.startswith("bothesis:")


def test_core_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MessageItem(role="user", content=(), unexpected=1)


def test_protocol_models_are_immutable() -> None:
    item = MessageItem(role="user", content=(InputText(text="hi"),))

    with pytest.raises(ValidationError):
        item.role = "assistant"


def test_extension_item_preserves_provider_type_and_fields() -> None:
    item = ItemAdapter.validate_python(
        {"type": "web_search_call", "id": "ws_1", "action": {"query": "policy"}}
    )

    assert isinstance(item, ExtensionItem)
    assert item.type == "web_search_call"
    assert item.model_dump()["action"] == {"query": "policy"}


def test_extension_types_cannot_shadow_specified_items_or_function_tools() -> None:
    with pytest.raises(ValidationError):
        ExtensionItem(type="message")
    with pytest.raises(ValidationError):
        ExtensionTool(type="function")


def test_failed_response_carries_a_typed_error() -> None:
    response = Response(
        id="resp_1",
        status="failed",
        error=ResponseError(code="rate_limited", message="slow down"),
    )

    assert response.error is not None
    assert response.error.code == "rate_limited"


def test_incomplete_response_carries_its_reason() -> None:
    response = Response(
        id="resp_1",
        status="incomplete",
        incomplete_details=IncompleteDetails(reason="max_output_tokens"),
    )

    assert response.incomplete_details is not None
    assert response.incomplete_details.reason == "max_output_tokens"
