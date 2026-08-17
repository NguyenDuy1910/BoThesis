"""Contract tests for the provider-neutral OpenResponses protocol."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from bothesis.agent.protocol import (
    AllowedTools,
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
    ReasoningSummaryText,
    Refusal,
    Response,
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseError,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseInProgressEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseRequest,
    ResponseStreamEventAdapter,
    ResponseUsage,
    ToolAdapter,
    ToolReference,
    pair_function_calls,
)

# ---------------------------------------------------------------------------
# Discriminated unions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"type": "message", "role": "user", "content": []}, MessageItem),
        ({"type": "reasoning"}, ReasoningItem),
        (
            {"type": "function_call", "call_id": "c1", "name": "search"},
            FunctionCallItem,
        ),
        (
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
            FunctionCallOutputItem,
        ),
        ({"type": "openrouter.reasoning_details"}, ExtensionItem),
    ],
)
def test_item_union_resolves_each_type(payload: dict, expected: type) -> None:
    assert isinstance(ItemAdapter.validate_python(payload), expected)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"type": "input_text", "text": "hi"}, InputText),
        ({"type": "input_image", "file_id": "file-1"}, InputImage),
        ({"type": "input_file", "file_id": "file-1"}, InputFile),
        ({"type": "output_text", "text": "hi"}, OutputText),
        ({"type": "refusal", "refusal": "no"}, Refusal),
    ],
)
def test_content_union_resolves_each_part(payload: dict, expected: type) -> None:
    message = MessageItem.model_validate(
        {"type": "message", "role": "user", "content": [payload]}
    )
    assert isinstance(message.content[0], expected)


def test_tool_union_separates_function_and_provider_tools() -> None:
    function_tool = ToolAdapter.validate_python(
        {"type": "function", "name": "search", "parameters": {"type": "object"}}
    )
    provider_tool = ToolAdapter.validate_python(
        {"type": "web_search", "search_context_size": "medium"}
    )
    assert isinstance(function_tool, FunctionTool)
    assert isinstance(provider_tool, ExtensionTool)
    assert provider_tool.model_dump()["search_context_size"] == "medium"


@pytest.mark.parametrize("mode", ["none", "auto", "required"])
def test_tool_choice_accepts_the_plain_modes(mode: str) -> None:
    assert ResponseRequest(input=(), tool_choice=mode).tool_choice == mode


def test_tool_choice_accepts_a_named_function_and_allowed_tools() -> None:
    named = ResponseRequest(input=(), tool_choice=FunctionToolChoice(name="search"))
    allowed = ResponseRequest(
        input=(),
        tool_choice=AllowedTools(
            mode="required", tools=(ToolReference(name="search"),)
        ),
    )
    assert isinstance(named.tool_choice, FunctionToolChoice)
    assert isinstance(allowed.tool_choice, AllowedTools)
    assert allowed.tool_choice.tools[0].name == "search"


def test_allowed_tools_requires_at_least_one_tool() -> None:
    with pytest.raises(ValidationError):
        AllowedTools(tools=())


# ---------------------------------------------------------------------------
# Serialization and deserialization
# ---------------------------------------------------------------------------


def test_request_round_trips_through_json() -> None:
    request = ResponseRequest(
        model="gpt-5.4-mini",
        instructions="Answer with citations.",
        input=(
            MessageItem(
                role="user",
                content=(
                    InputText(text="Summarize this"),
                    InputImage(image_url="https://example.test/chart.png"),
                    InputFile(file_id="file-1", filename="policy.pdf"),
                ),
            ),
        ),
        tools=(FunctionTool(name="search", parameters={"type": "object"}),),
        tool_choice="auto",
        max_output_tokens=512,
        temperature=0.2,
        metadata={"request_id": "r-1"},
        provider_options={"reasoning": {"effort": "low"}},
    )

    restored = ResponseRequest.model_validate_json(request.model_dump_json())

    assert restored == request
    assert restored.provider_options == {"reasoning": {"effort": "low"}}


def test_response_round_trips_through_json() -> None:
    response = Response(
        id="resp-1",
        created_at=1_770_000_000,
        status="incomplete",
        model="gpt-5.4-mini",
        output=(
            ReasoningItem(
                id="rs-1", summary=(ReasoningSummaryText(text="Checking policy"),)
            ),
            MessageItem(
                role="assistant",
                content=(
                    OutputText(
                        text="Employees receive 20 days",
                        annotations=({"type": "file", "file": {"hash": "h1"}},),
                    ),
                ),
            ),
        ),
        usage=ResponseUsage(
            input_tokens=30,
            input_tokens_details=InputTokensDetails(cached_tokens=5),
            output_tokens=9,
            total_tokens=39,
        ),
        incomplete_details=IncompleteDetails(reason="max_output_tokens"),
    )

    restored = Response.model_validate_json(response.model_dump_json())

    assert restored == response
    assert restored.output_text == "Employees receive 20 days"
    assert restored.output_annotations == ({"type": "file", "file": {"hash": "h1"}},)
    assert restored.output[0].summary_text == "Checking policy"


def test_core_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Response(status="completed", finish_reason="stop")


def test_protocol_models_are_immutable() -> None:
    item = FunctionCallItem(call_id="c1", name="search")
    with pytest.raises(ValidationError):
        item.name = "other"


# ---------------------------------------------------------------------------
# Function calls and their correlation
# ---------------------------------------------------------------------------


def test_function_call_arguments_decode_to_a_json_object() -> None:
    call = FunctionCallItem(
        call_id="c1", name="search", arguments='{"query":"leave policy"}'
    )
    assert call.parsed_arguments() == {"query": "leave policy"}
    assert FunctionCallItem(call_id="c1", name="search").parsed_arguments() == {}


@pytest.mark.parametrize("arguments", ["{not json}", '"a string"', "[1, 2]"])
def test_function_call_arguments_reject_non_objects(arguments: str) -> None:
    call = FunctionCallItem(call_id="c1", name="search", arguments=arguments)
    with pytest.raises(ValueError):
        call.parsed_arguments()


def test_function_calls_correlate_with_their_outputs_by_call_id() -> None:
    first = FunctionCallItem(call_id="c1", name="search")
    second = FunctionCallItem(call_id="c2", name="search")
    output = FunctionCallOutputItem(call_id="c1", output="20 days")

    pairs = pair_function_calls((first, output, second))

    assert pairs == ((first, output), (second, None))


def test_response_exposes_function_calls_in_output_order() -> None:
    response = Response(
        status="completed",
        output=(
            FunctionCallItem(call_id="c1", name="search"),
            MessageItem(role="assistant", content=(OutputText(text="checking"),)),
            FunctionCallItem(call_id="c2", name="fetch"),
        ),
    )
    assert [call.call_id for call in response.function_calls] == ["c1", "c2"]
    assert response.output_text == "checking"


def test_function_call_identity_is_required() -> None:
    with pytest.raises(ValidationError):
        FunctionCallItem(call_id="", name="search")
    with pytest.raises(ValidationError):
        FunctionCallOutputItem(call_id="c1", output="ok", type="message")


# ---------------------------------------------------------------------------
# Extension items
# ---------------------------------------------------------------------------


def test_extension_item_preserves_provider_type_and_fields() -> None:
    item = ItemAdapter.validate_python(
        {
            "type": "openrouter.reasoning_details",
            "id": "rd-1",
            "details": [{"type": "reasoning.summary", "summary": "checking"}],
        }
    )
    assert isinstance(item, ExtensionItem)
    assert item.type == "openrouter.reasoning_details"
    assert item.model_dump()["details"] == [
        {"type": "reasoning.summary", "summary": "checking"}
    ]


def test_extension_items_survive_a_response_round_trip() -> None:
    response = Response(
        status="completed",
        output=(ExtensionItem(type="vendor.trace", payload={"span": "s-1"}),),
    )
    restored = Response.model_validate_json(response.model_dump_json())
    assert restored == response
    assert restored.output[0].model_dump()["payload"] == {"span": "s-1"}


def test_extension_types_cannot_shadow_core_items_or_function_tools() -> None:
    with pytest.raises(ValidationError):
        ExtensionItem(type="function_call")
    with pytest.raises(ValidationError):
        ExtensionTool(type="function")


# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------


def test_stream_event_union_resolves_every_event_type() -> None:
    snapshot = Response(status="in_progress")
    events = [
        ResponseCreatedEvent(sequence_number=0, response=snapshot),
        ResponseInProgressEvent(sequence_number=1, response=snapshot),
        ResponseOutputItemAddedEvent(
            sequence_number=2,
            output_index=0,
            item=FunctionCallItem(call_id="c1", name="search"),
        ),
        ResponseFunctionCallArgumentsDeltaEvent(
            sequence_number=3, item_id="fc-1", output_index=0, delta='{"query"'
        ),
        ResponseFunctionCallArgumentsDoneEvent(
            sequence_number=4,
            item_id="fc-1",
            output_index=0,
            arguments='{"query":"leave"}',
        ),
        ResponseOutputItemDoneEvent(
            sequence_number=5,
            output_index=0,
            item=FunctionCallItem(
                call_id="c1", name="search", arguments='{"query":"leave"}'
            ),
        ),
        ResponseOutputTextDeltaEvent(
            sequence_number=6, item_id="msg-1", output_index=1, delta="20 days"
        ),
        ResponseOutputTextDoneEvent(
            sequence_number=7, item_id="msg-1", output_index=1, text="20 days"
        ),
        ResponseCompletedEvent(
            sequence_number=8, response=Response(status="completed")
        ),
    ]

    for event in events:
        restored = ResponseStreamEventAdapter.validate_json(event.model_dump_json())
        assert restored == event
        assert type(restored) is type(event)

    assert [event.type for event in events] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.output_text.delta",
        "response.output_text.done",
        "response.completed",
    ]


def test_failed_event_carries_the_response_error() -> None:
    event = ResponseFailedEvent(
        sequence_number=1,
        response=Response(
            status="failed",
            error=ResponseError(code="rate_limit", message="slow down"),
        ),
    )
    restored = ResponseStreamEventAdapter.validate_json(event.model_dump_json())
    assert restored.response.error == ResponseError(
        code="rate_limit", message="slow down"
    )


def test_output_item_events_carry_extension_items() -> None:
    event = ResponseOutputItemAddedEvent(
        sequence_number=1,
        output_index=0,
        item=ExtensionItem(type="vendor.custom", note="keep"),
    )
    restored = ResponseStreamEventAdapter.validate_json(event.model_dump_json())
    assert isinstance(restored.item, ExtensionItem)
    assert restored.item.model_dump()["note"] == "keep"


def test_stream_events_require_a_non_negative_sequence_number() -> None:
    with pytest.raises(ValidationError):
        ResponseOutputTextDeltaEvent(
            sequence_number=-1, item_id="msg-1", output_index=0, delta="x"
        )
