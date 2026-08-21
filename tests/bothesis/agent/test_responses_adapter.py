"""Native ``/responses`` mapping tests for the one shared adapter.

Every supported provider serves ``POST /responses`` in OpenResponses format, so
the projection is provider-independent: these tests drive the adapter with real
SDK event objects and assert the same result for OpenAI and OpenRouter. What is
provider-specific — base URL, attribution headers, non-specified request options
— lives in the transports and is covered by their own modules.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TESTS_ROOT))
sys.path.insert(0, str(_TESTS_ROOT.parent / "backend"))

from openai.types.responses import (
    ResponseErrorEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseRefusalDeltaEvent,
)
from openai.types.responses.response_function_web_search import (
    ActionSearch,
    ResponseFunctionWebSearch,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)

from native_responses import (
    ScriptedResponsesTransport,
    completed,
    created,
    failed,
    function_call,
    incomplete,
    message,
    native_response,
    reasoning,
)

from bothesis.agent.protocol import (
    ExtensionItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    FunctionTool,
    InputText,
    MessageItem,
    OutputText,
    ReasoningItem,
    ReasoningText,
    Refusal,
    ResponseRequest,
    SummaryText,
)
from bothesis.agent.reducer import ResponseReducer
from bothesis.agent.transports import RESPONSES_PROVIDERS, response_stream
from bothesis.agent.transports.responses_adapter import ResponsesStream, render_input

PROVIDERS = sorted(RESPONSES_PROVIDERS)


async def canonical(
    events: list[Any],
    request: ResponseRequest | None = None,
    *,
    provider: str = "openrouter",
):
    transport = ScriptedResponsesTransport([events], provider=provider)
    stream = ResponsesStream(transport)
    return transport, [
        event async for event in stream.stream(request or ResponseRequest(input=()))
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_message_lifecycle_maps_one_native_event_to_one_canonical_event(
    provider: str,
) -> None:
    _, events = await canonical(
        [
            *created(),
            *message(
                item_id="msg_1",
                output_index=0,
                deltas=["Hel", "lo"],
                phase="final_answer",
            ),
            *completed(),
        ],
        provider=provider,
    )

    assert [event.type for event in events] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [event.delta for event in events if event.type.endswith("text.delta")] == [
        "Hel",
        "lo",
    ]
    assert events[-2].item.phase == "final_answer"
    assert events[-1].response.status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_reasoning_events_are_renamed_to_the_specified_types(
    provider: str,
) -> None:
    """Both providers emit ``response.reasoning_text.*``; the spec says ``reasoning``."""

    _, events = await canonical(
        reasoning(
            item_id="rs_1",
            output_index=0,
            summary="check the policy",
            text="raw thought",
            encrypted_content="blob",
        ),
        provider=provider,
    )

    assert [event.type for event in events] == [
        "response.output_item.added",
        "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.done",
        "response.reasoning.delta",
        "response.reasoning.done",
        "response.output_item.done",
    ]
    item = events[-1].item
    assert isinstance(item, ReasoningItem)
    assert item.content == (ReasoningText(text="raw thought"),)
    assert item.summary == (SummaryText(text="check the policy"),)
    # ``encrypted_content`` is the specified continuation blob, so a reasoning
    # item needs no BoThesis-specific field to replay.
    assert item.encrypted_content == "blob"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_function_call_arguments_stream_through_unchanged(provider: str) -> None:
    _, events = await canonical(
        function_call(
            item_id="fc_1",
            output_index=0,
            call_id="call-1",
            name="knowledge_search",
            argument_deltas=['{"queries":', '["policy"]}'],
        ),
        provider=provider,
    )

    assert [event.type for event in events] == [
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
    ]
    assert isinstance(events[0].item, FunctionCallItem)
    assert events[0].item.call_id == "call-1"
    assert events[-1].item.parsed_arguments() == {"queries": ["policy"]}


@pytest.mark.asyncio
async def test_both_providers_project_the_same_stream_identically() -> None:
    """The projection has no provider dimension; only the transports differ."""

    script = [
        *created(),
        *reasoning(item_id="rs_1", output_index=0, summary="plan"),
        *message(item_id="msg_1", output_index=1, deltas=["Checking. "], phase="commentary"),
        *function_call(
            item_id="fc_1",
            output_index=2,
            call_id="call-1",
            name="lookup",
            argument_deltas=['{"term":"x"}'],
        ),
        *completed(),
    ]
    projections = {}
    for provider in PROVIDERS:
        _, events = await canonical(list(script), provider=provider)
        projections[provider] = [event.model_dump(mode="json") for event in events]

    assert projections["openai"] == projections["openrouter"]


@pytest.mark.asyncio
async def test_the_canonical_stream_reconstructs_through_the_reducer() -> None:
    _, events = await canonical(
        [
            *created(),
            *reasoning(item_id="rs_1", output_index=0, text="thinking"),
            *message(item_id="msg_1", output_index=1, deltas=["Checking. "]),
            *function_call(
                item_id="fc_1",
                output_index=2,
                call_id="call-1",
                name="search",
                argument_deltas=['{"q":"x"}'],
            ),
            *completed(),
        ]
    )
    reducer = ResponseReducer()
    for event in events:
        reducer.apply(event)
    response = reducer.response

    assert [item.type for item in response.output] == [
        "reasoning",
        "message",
        "function_call",
    ]
    assert response.output[0].reasoning_text == "thinking"
    assert response.output_text == "Checking. "
    assert response.function_calls[0].parsed_arguments() == {"q": "x"}
    assert response.messages[0].phase == "commentary"


@pytest.mark.asyncio
async def test_created_response_carries_the_previous_response_id() -> None:
    """The chain is stamped by the adapter, never sent to the provider."""

    transport, events = await canonical(
        created(),
        ResponseRequest(input=(), previous_response_id="resp_earlier"),
    )

    assert events[0].response.previous_response_id == "resp_earlier"
    assert "previous_response_id" not in transport.requests[0]


@pytest.mark.asyncio
async def test_refusal_and_hosted_tool_items_are_handled() -> None:
    hosted = ResponseFunctionWebSearch(
        id="ws_1",
        type="web_search_call",
        status="completed",
        action=ActionSearch(type="search", query="policy"),
    )
    _, events = await canonical(
        [
            ResponseRefusalDeltaEvent(
                type="response.refusal.delta",
                sequence_number=0,
                item_id="msg_1",
                output_index=0,
                content_index=0,
                delta="cannot help",
            ),
            ResponseOutputItemDoneEvent(
                type="response.output_item.done",
                sequence_number=1,
                output_index=1,
                item=ResponseOutputMessage(
                    id="msg_1",
                    role="assistant",
                    status="completed",
                    type="message",
                    content=[
                        ResponseOutputRefusal(type="refusal", refusal="cannot help")
                    ],
                ),
            ),
            ResponseOutputItemDoneEvent(
                type="response.output_item.done",
                sequence_number=2,
                output_index=2,
                item=hosted,
            ),
        ]
    )

    assert events[0].type == "response.refusal.delta"
    assert isinstance(events[1].item.content[0], Refusal)
    assert isinstance(events[2].item, ExtensionItem)
    assert events[2].item.type == "web_search_call"
    assert events[2].item.model_dump()["action"]["query"] == "policy"


@pytest.mark.asyncio
async def test_provider_only_events_are_not_invented_into_the_stream() -> None:
    """OpenRouter router events and hosted-tool lifecycles are simply dropped.

    The SDK never rejects an unknown event type; it preserves ``type``, which is
    what the adapter dispatches on.
    """

    class NativeRouterEvent:
        type = "response.fusion_call.panel.added"
        sequence_number = 0
        output_index = 0
        item_id = "fusion_1"

    class NativeWebSearchEvent:
        type = "response.web_search_call.searching"
        sequence_number = 1
        item_id = "ws_1"
        output_index = 0

    _, events = await canonical([NativeRouterEvent(), NativeWebSearchEvent()])

    assert events == []


@pytest.mark.asyncio
async def test_incomplete_and_failed_responses_map_to_their_events() -> None:
    _, truncated = await canonical(incomplete("max_output_tokens"))
    _, broken = await canonical(failed("server_error", "upstream failure"))

    assert truncated[0].type == "response.incomplete"
    assert truncated[0].response.incomplete_details.reason == "max_output_tokens"
    assert broken[0].type == "response.failed"
    assert broken[0].response.error.code == "server_error"


@pytest.mark.asyncio
async def test_native_error_event_maps_to_the_specified_error_event() -> None:
    _, events = await canonical(
        [
            ResponseErrorEvent(
                type="error",
                sequence_number=0,
                code="rate_limit",
                message="slow down",
                param=None,
            )
        ]
    )

    assert events[0].type == "error"
    assert events[0].error.message == "slow down"
    assert events[0].error.code == "rate_limit"


@pytest.mark.asyncio
async def test_usage_is_mapped_onto_the_canonical_response() -> None:
    _, events = await canonical(
        completed(
            usage=ResponseUsage(
                input_tokens=10,
                input_tokens_details=InputTokensDetails(
                    cached_tokens=4, cache_write_tokens=0
                ),
                output_tokens=6,
                output_tokens_details=OutputTokensDetails(reasoning_tokens=2),
                total_tokens=16,
            )
        )
    )
    usage = events[0].response.usage

    assert usage.input_tokens_details.cached_tokens == 4
    assert usage.output_tokens_details.reasoning_tokens == 2
    assert usage.total_tokens == 16


@pytest.mark.asyncio
async def test_specified_request_fields_are_rendered_as_native_parameters() -> None:
    request = ResponseRequest(
        input=(MessageItem(role="user", content=(InputText(text="hi"),)),),
        model="test-model",
        instructions="be brief",
        tools=(FunctionTool(name="search", parameters={"type": "object"}, strict=True),),
        tool_choice="auto",
        parallel_tool_calls=True,
        temperature=0.2,
        max_output_tokens=256,
    )
    transport, _ = await canonical([], request)
    sent = transport.requests[0]

    assert sent["model"] == "test-model"
    assert sent["instructions"] == "be brief"
    assert sent["temperature"] == 0.2
    assert sent["max_output_tokens"] == 256
    assert sent["parallel_tool_calls"] is True
    assert sent["tools"] == [
        {
            "type": "function",
            "name": "search",
            "description": "",
            "parameters": {"type": "object"},
            "strict": True,
        }
    ]
    assert sent["input"] == [{"type": "message", "role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_provider_options_ride_in_extra_body() -> None:
    """Non-specified options stay opaque: the adapter never names them."""

    request = ResponseRequest(
        input=(),
        provider_options={
            "provider": {"order": ["openai"]},
            "plugins": [{"id": "web"}],
            "top_k": 40,
        },
    )
    transport, _ = await canonical([], request)
    sent = transport.requests[0]

    assert sent["extra_body"] == {
        "provider": {"order": ["openai"]},
        "plugins": [{"id": "web"}],
        "top_k": 40,
    }
    assert "provider" not in sent
    assert "top_k" not in sent


def test_render_input_replays_every_item_type() -> None:
    rendered = render_input(
        (
            MessageItem(role="user", content=(InputText(text="hi"),)),
            ReasoningItem(
                id="rs_1",
                summary=(SummaryText(text="plan"),),
                content=(ReasoningText(text="raw"),),
                encrypted_content="blob",
            ),
            MessageItem(
                role="assistant",
                phase="commentary",
                content=(
                    OutputText(
                        text="Searching.",
                        annotations=({"type": "bothesis:document_citation"},),
                    ),
                ),
            ),
            FunctionCallItem(
                id="fc_1", call_id="call-1", name="search", arguments='{"q":"a"}'
            ),
            FunctionCallOutputItem(call_id="call-1", output="found"),
        )
    )

    assert rendered[0] == {"type": "message", "role": "user", "content": "hi"}
    # Reasoning input carries summary and encrypted content only.
    assert rendered[1] == {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "plan"}],
        "id": "rs_1",
        "encrypted_content": "blob",
    }
    # Phase is preserved, annotations are not: a provider rejects foreign types.
    assert rendered[2] == {
        "type": "message",
        "role": "assistant",
        "content": "Searching.",
        "phase": "commentary",
    }
    assert rendered[3] == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "search",
        "arguments": '{"q":"a"}',
        "id": "fc_1",
    }
    assert rendered[4] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "found",
    }


def test_a_transport_without_responses_support_is_rejected() -> None:
    class ChatCompletionsOnlyTransport:
        provider = "openrouter"
        model = "test-model"

    with pytest.raises(ValueError, match="does not serve /responses"):
        response_stream(ChatCompletionsOnlyTransport())

    class UnknownProviderTransport:
        provider = "anthropic"
        model = "test-model"

        async def stream_response(self, **_: Any) -> Any:
            return None

    with pytest.raises(ValueError, match="unsupported model transport provider"):
        response_stream(UnknownProviderTransport())


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_the_adapter_reports_the_wrapped_provider(provider: str) -> None:
    transport = ScriptedResponsesTransport([], provider=provider)
    stream = response_stream(transport)

    assert stream.provider == provider
    assert stream.model == "test-model"
    assert native_response().model == "test-model"
