"""Response reconstruction tests for :class:`ResponseReducer`.

The reducer is the only component allowed to rebuild response state, and it may
use nothing but the specified addressing fields. These tests drive it with
hand-written canonical event streams so no provider behaviour can leak in.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from bothesis.agent.protocol import (
    ErrorEvent,
    ErrorPayload,
    FunctionCallItem,
    IncompleteDetails,
    MessageItem,
    OutputText,
    ReasoningItem,
    ReasoningText,
    Refusal,
    Response,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseError,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseReasoningDeltaEvent,
    ResponseReasoningDoneEvent,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseRefusalDeltaEvent,
    ResponseRefusalDoneEvent,
    SummaryText,
)
from bothesis.agent.reducer import ResponseReducer


def message_lifecycle(
    *,
    item_id: str,
    output_index: int,
    deltas: tuple[str, ...],
    phase: str | None = None,
) -> list[object]:
    """The canonical event order the specification prescribes for one message."""

    text = "".join(deltas)
    return [
        ResponseOutputItemAddedEvent(
            output_index=output_index,
            item=MessageItem(
                id=item_id, role="assistant", status="in_progress", content=()
            ),
        ),
        ResponseContentPartAddedEvent(
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            part=OutputText(text=""),
        ),
        *(
            ResponseOutputTextDeltaEvent(
                item_id=item_id,
                output_index=output_index,
                content_index=0,
                delta=delta,
            )
            for delta in deltas
        ),
        ResponseOutputTextDoneEvent(
            item_id=item_id, output_index=output_index, content_index=0, text=text
        ),
        ResponseContentPartDoneEvent(
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            part=OutputText(text=text),
        ),
        ResponseOutputItemDoneEvent(
            output_index=output_index,
            item=MessageItem(
                id=item_id,
                role="assistant",
                status="completed",
                phase=phase,
                content=(OutputText(text=text),),
            ),
        ),
    ]


def reduce_all(events) -> tuple[ResponseReducer, list[object]]:
    reducer = ResponseReducer()
    return reducer, [reducer.apply(event) for event in events]


def test_reducer_rebuilds_a_streamed_message_from_its_deltas() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        *message_lifecycle(item_id="msg_1", output_index=0, deltas=("Hel", "lo ", "world")),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    reducer, projected = reduce_all(events)
    response = projected[-1].response

    assert response is reducer.response or response == reducer.response
    assert response.status == "completed"
    assert response.output_text == "Hello world"
    assert response.output[0].content[0].text == "Hello world"
    assert response.output[0].status == "completed"


def test_reducer_keeps_streamed_text_when_the_final_item_omits_it() -> None:
    """A provider may repeat only the item shell in ``output_item.done``."""

    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        ResponseOutputItemAddedEvent(
            output_index=0,
            item=MessageItem(id="msg_1", role="assistant", content=()),
        ),
        ResponseOutputTextDeltaEvent(
            item_id="msg_1", output_index=0, content_index=0, delta="streamed"
        ),
        ResponseOutputItemDoneEvent(
            output_index=0,
            item=MessageItem(
                id="msg_1", role="assistant", content=(OutputText(text=""),)
            ),
        ),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)

    assert projected[-1].response.output_text == "streamed"


def test_reducer_addresses_each_content_index_independently() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        ResponseOutputItemAddedEvent(
            output_index=0, item=MessageItem(id="msg_1", role="assistant", content=())
        ),
        ResponseContentPartAddedEvent(
            item_id="msg_1", output_index=0, content_index=0, part=OutputText(text="")
        ),
        ResponseContentPartAddedEvent(
            item_id="msg_1", output_index=0, content_index=1, part=Refusal(refusal="")
        ),
        ResponseOutputTextDeltaEvent(
            item_id="msg_1", output_index=0, content_index=0, delta="answer"
        ),
        ResponseRefusalDeltaEvent(
            item_id="msg_1", output_index=0, content_index=1, delta="cannot"
        ),
        ResponseRefusalDoneEvent(
            item_id="msg_1", output_index=0, content_index=1, refusal="cannot help"
        ),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)
    content = projected[-1].response.output[0].content

    assert [part.type for part in content] == ["output_text", "refusal"]
    assert content[0].text == "answer"
    assert content[1].refusal == "cannot help"


def test_reducer_orders_items_by_output_index_not_arrival() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        ResponseOutputItemAddedEvent(
            output_index=1,
            item=FunctionCallItem(
                id="fc_1", call_id="call-1", name="search", status="in_progress"
            ),
        ),
        ResponseOutputItemAddedEvent(
            output_index=0,
            item=MessageItem(id="msg_1", role="assistant", content=()),
        ),
        ResponseOutputTextDeltaEvent(
            item_id="msg_1", output_index=0, content_index=0, delta="Searching"
        ),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)
    output = projected[-1].response.output

    assert [item.type for item in output] == ["message", "function_call"]


def test_reducer_assembles_function_call_arguments_from_deltas() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        ResponseOutputItemAddedEvent(
            output_index=0,
            item=FunctionCallItem(
                id="fc_1", call_id="call-1", name="search", status="in_progress"
            ),
        ),
        ResponseFunctionCallArgumentsDeltaEvent(
            item_id="fc_1", output_index=0, delta='{"queries":'
        ),
        ResponseFunctionCallArgumentsDeltaEvent(
            item_id="fc_1", output_index=0, delta='["policy"]}'
        ),
        ResponseFunctionCallArgumentsDoneEvent(
            item_id="fc_1", output_index=0, arguments='{"queries":["policy"]}'
        ),
        ResponseOutputItemDoneEvent(
            output_index=0,
            item=FunctionCallItem(
                id="fc_1",
                call_id="call-1",
                name="search",
                arguments='{"queries":["policy"]}',
                status="completed",
            ),
        ),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)
    call = projected[-1].response.function_calls[0]

    assert call.parsed_arguments() == {"queries": ["policy"]}
    assert call.status == "completed"


def test_reducer_rebuilds_a_reasoning_item_from_its_lifecycle() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        ResponseOutputItemAddedEvent(
            output_index=0, item=ReasoningItem(id="rs_1", status="in_progress")
        ),
        ResponseReasoningSummaryPartAddedEvent(
            item_id="rs_1", output_index=0, summary_index=0, part=SummaryText(text="")
        ),
        ResponseReasoningSummaryTextDeltaEvent(
            item_id="rs_1", output_index=0, summary_index=0, delta="check the policy"
        ),
        ResponseReasoningDeltaEvent(
            item_id="rs_1", output_index=0, content_index=0, delta="raw "
        ),
        ResponseReasoningDeltaEvent(
            item_id="rs_1", output_index=0, content_index=0, delta="thought"
        ),
        ResponseReasoningDoneEvent(
            item_id="rs_1", output_index=0, content_index=0, text="raw thought"
        ),
        ResponseOutputItemDoneEvent(
            output_index=0,
            item=ReasoningItem(id="rs_1", status="completed", encrypted_content="blob"),
        ),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)
    reasoning = projected[-1].response.output[0]

    assert isinstance(reasoning, ReasoningItem)
    assert reasoning.reasoning_text == "raw thought"
    assert reasoning.summary_text == "check the policy"
    assert reasoning.encrypted_content == "blob"
    assert reasoning.content == (ReasoningText(text="raw thought"),)


def test_reducer_places_annotations_at_their_annotation_index() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        ResponseOutputItemAddedEvent(
            output_index=0, item=MessageItem(id="msg_1", role="assistant", content=())
        ),
        ResponseOutputTextDeltaEvent(
            item_id="msg_1", output_index=0, content_index=0, delta="grounded"
        ),
        ResponseOutputTextAnnotationAddedEvent(
            item_id="msg_1",
            output_index=0,
            content_index=0,
            annotation_index=0,
            annotation={"type": "bothesis:document_citation", "citation": {"id": "a"}},
        ),
        ResponseOutputTextAnnotationAddedEvent(
            item_id="msg_1",
            output_index=0,
            content_index=0,
            annotation_index=1,
            annotation={"type": "bothesis:document_citation", "citation": {"id": "b"}},
        ),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)
    annotations = projected[-1].response.output_annotations

    assert [annotation["citation"]["id"] for annotation in annotations] == ["a", "b"]


def test_reducer_resolves_commentary_phase_for_a_response_with_tool_calls() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        *message_lifecycle(item_id="msg_1", output_index=0, deltas=("Searching.",)),
        ResponseOutputItemDoneEvent(
            output_index=1,
            item=FunctionCallItem(
                id="fc_1",
                call_id="call-1",
                name="search",
                arguments="{}",
                status="completed",
            ),
        ),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)
    response = projected[-1].response

    assert response.messages[0].phase == "commentary"
    assert response.final_answer_text == ""
    assert response.commentary_text == "Searching."


def test_reducer_resolves_final_answer_phase_without_tool_calls() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        *message_lifecycle(item_id="msg_1", output_index=0, deltas=("42",)),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)

    assert projected[-1].response.messages[0].phase == "final_answer"


def test_reducer_keeps_a_phase_the_provider_declared() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        *message_lifecycle(
            item_id="msg_1", output_index=0, deltas=("note",), phase="commentary"
        ),
        ResponseCompletedEvent(response=Response(id="resp_1", status="completed")),
    ]

    _, projected = reduce_all(events)

    assert projected[-1].response.messages[0].phase == "commentary"


def test_reducer_settles_an_incomplete_response_with_its_reason() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        ResponseOutputItemAddedEvent(
            output_index=0, item=MessageItem(id="msg_1", role="assistant", content=())
        ),
        ResponseOutputTextDeltaEvent(
            item_id="msg_1", output_index=0, content_index=0, delta="partial"
        ),
        ResponseIncompleteEvent(
            response=Response(
                id="resp_1",
                status="incomplete",
                incomplete_details=IncompleteDetails(reason="max_output_tokens"),
            )
        ),
    ]

    _, projected = reduce_all(events)
    response = projected[-1].response

    assert response.status == "incomplete"
    assert response.incomplete_details.reason == "max_output_tokens"
    assert response.output_text == "partial"


def test_reducer_settles_a_failed_response_with_its_error() -> None:
    events = [
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress")),
        ResponseFailedEvent(
            response=Response(
                id="resp_1",
                status="failed",
                error=ResponseError(code="rate_limited", message="slow down"),
            )
        ),
    ]

    _, projected = reduce_all(events)
    response = projected[-1].response

    assert response.status == "failed"
    assert response.error.code == "rate_limited"


def test_reducer_marks_the_response_failed_on_a_stream_error_event() -> None:
    reducer = ResponseReducer()
    reducer.apply(
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress"))
    )
    reducer.apply(ErrorEvent(error=ErrorPayload(message="upstream down", code="502")))

    assert reducer.response.status == "failed"
    assert reducer.response.error.message == "upstream down"


def test_reducer_seeds_items_from_a_non_streamed_snapshot() -> None:
    """A snapshot that already carries output is reconstructed as-is."""

    reducer = ResponseReducer()
    reducer.apply(
        ResponseCompletedEvent(
            response=Response(
                id="resp_1",
                status="completed",
                output=(
                    MessageItem(
                        id="msg_1",
                        role="assistant",
                        status="completed",
                        content=(OutputText(text="direct"),),
                    ),
                ),
            )
        )
    )

    assert reducer.response.output_text == "direct"
    assert reducer.response.messages[0].phase == "final_answer"


def test_reducer_resolves_an_item_id_to_its_output_index() -> None:
    reducer = ResponseReducer()
    reducer.apply(
        ResponseCreatedEvent(response=Response(id="resp_1", status="in_progress"))
    )
    reducer.apply(
        ResponseOutputItemAddedEvent(
            output_index=3, item=MessageItem(id="msg_9", role="assistant", content=())
        )
    )

    assert reducer.output_index_of("msg_9") == 3
    assert reducer.output_index_of("absent") is None
