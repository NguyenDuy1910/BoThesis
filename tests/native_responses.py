"""Builders for native ``/responses`` streaming events, shared by agent tests.

Every provider BoThesis supports emits the same OpenResponses-format events, so
these builders describe one provider stream and are reused for all of them. They
produce real OpenAI SDK event objects, which is exactly what both transports
hand to the adapter.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openai.types.responses import (
    Response as NativeResponse,
)
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionToolCall,
    ResponseInProgressEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningTextDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
)
from openai.types.responses.response_reasoning_item import Content, Summary
from openai.types.responses.response_reasoning_summary_text_delta_event import (
    ResponseReasoningSummaryTextDeltaEvent,
)
from openai.types.responses.response_reasoning_summary_text_done_event import (
    ResponseReasoningSummaryTextDoneEvent,
)


def native_response(**overrides: Any) -> NativeResponse:
    """One native response envelope with the SDK's required fields filled in."""

    payload: dict[str, Any] = {
        "id": "resp_native",
        "created_at": 1.0,
        "model": "test-model",
        "object": "response",
        "output": [],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": "in_progress",
    }
    payload.update(overrides)
    return NativeResponse(**payload)


class _Sequencer:
    """Assign the monotonic ``sequence_number`` a provider stream carries."""

    def __init__(self) -> None:
        self._next = 0

    def take(self) -> int:
        value = self._next
        self._next += 1
        return value


def created(response_id: str = "resp_native") -> list[Any]:
    seq = _Sequencer()
    return [
        ResponseCreatedEvent(
            type="response.created",
            sequence_number=seq.take(),
            response=native_response(id=response_id),
        ),
        ResponseInProgressEvent(
            type="response.in_progress",
            sequence_number=seq.take(),
            response=native_response(id=response_id),
        ),
    ]


def message(
    *,
    item_id: str,
    output_index: int,
    deltas: Sequence[str],
    phase: str | None = None,
) -> list[Any]:
    """The specified event order for one streamed assistant message."""

    seq = _Sequencer()
    text = "".join(deltas)
    shell = ResponseOutputMessage(
        id=item_id, role="assistant", status="in_progress", type="message", content=[]
    )
    events: list[Any] = [
        ResponseOutputItemAddedEvent(
            type="response.output_item.added",
            sequence_number=seq.take(),
            output_index=output_index,
            item=shell,
        ),
        ResponseContentPartAddedEvent(
            type="response.content_part.added",
            sequence_number=seq.take(),
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            part=ResponseOutputText(type="output_text", text="", annotations=[]),
        ),
    ]
    events.extend(
        ResponseTextDeltaEvent(
            type="response.output_text.delta",
            sequence_number=seq.take(),
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            delta=delta,
            logprobs=[],
        )
        for delta in deltas
    )
    events.append(
        ResponseTextDoneEvent(
            type="response.output_text.done",
            sequence_number=seq.take(),
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            text=text,
            logprobs=[],
        )
    )
    part = ResponseOutputText(type="output_text", text=text, annotations=[])
    events.append(
        ResponseContentPartDoneEvent(
            type="response.content_part.done",
            sequence_number=seq.take(),
            item_id=item_id,
            output_index=output_index,
            content_index=0,
            part=part,
        )
    )
    events.append(
        ResponseOutputItemDoneEvent(
            type="response.output_item.done",
            sequence_number=seq.take(),
            output_index=output_index,
            item=shell.model_copy(
                update={"status": "completed", "phase": phase, "content": [part]}
            ),
        )
    )
    return events


def function_call(
    *,
    item_id: str,
    output_index: int,
    call_id: str,
    name: str,
    argument_deltas: Sequence[str],
) -> list[Any]:
    """The specified event order for one streamed function call."""

    seq = _Sequencer()
    arguments = "".join(argument_deltas)
    shell = ResponseFunctionToolCall(
        id=item_id,
        call_id=call_id,
        name=name,
        arguments="",
        type="function_call",
        status="in_progress",
    )
    events: list[Any] = [
        ResponseOutputItemAddedEvent(
            type="response.output_item.added",
            sequence_number=seq.take(),
            output_index=output_index,
            item=shell,
        )
    ]
    events.extend(
        ResponseFunctionCallArgumentsDeltaEvent(
            type="response.function_call_arguments.delta",
            sequence_number=seq.take(),
            item_id=item_id,
            output_index=output_index,
            delta=delta,
        )
        for delta in argument_deltas
    )
    events.append(
        ResponseFunctionCallArgumentsDoneEvent(
            type="response.function_call_arguments.done",
            sequence_number=seq.take(),
            item_id=item_id,
            output_index=output_index,
            name=name,
            arguments=arguments,
        )
    )
    events.append(
        ResponseOutputItemDoneEvent(
            type="response.output_item.done",
            sequence_number=seq.take(),
            output_index=output_index,
            item=shell.model_copy(
                update={"status": "completed", "arguments": arguments}
            ),
        )
    )
    return events


def reasoning(
    *,
    item_id: str,
    output_index: int,
    summary: str | None = None,
    text: str | None = None,
    encrypted_content: str | None = None,
) -> list[Any]:
    """The specified event order for one streamed reasoning item."""

    seq = _Sequencer()
    shell = ResponseReasoningItem(
        id=item_id, type="reasoning", summary=[], status="in_progress"
    )
    events: list[Any] = [
        ResponseOutputItemAddedEvent(
            type="response.output_item.added",
            sequence_number=seq.take(),
            output_index=output_index,
            item=shell,
        )
    ]
    if summary is not None:
        events.append(
            ResponseReasoningSummaryTextDeltaEvent(
                type="response.reasoning_summary_text.delta",
                sequence_number=seq.take(),
                item_id=item_id,
                output_index=output_index,
                summary_index=0,
                delta=summary,
            )
        )
        events.append(
            ResponseReasoningSummaryTextDoneEvent(
                type="response.reasoning_summary_text.done",
                sequence_number=seq.take(),
                item_id=item_id,
                output_index=output_index,
                summary_index=0,
                text=summary,
            )
        )
    if text is not None:
        events.append(
            ResponseReasoningTextDeltaEvent(
                type="response.reasoning_text.delta",
                sequence_number=seq.take(),
                item_id=item_id,
                output_index=output_index,
                content_index=0,
                delta=text,
            )
        )
        events.append(
            ResponseReasoningTextDoneEvent(
                type="response.reasoning_text.done",
                sequence_number=seq.take(),
                item_id=item_id,
                output_index=output_index,
                content_index=0,
                text=text,
            )
        )
    events.append(
        ResponseOutputItemDoneEvent(
            type="response.output_item.done",
            sequence_number=seq.take(),
            output_index=output_index,
            item=shell.model_copy(
                update={
                    "status": "completed",
                    "summary": [Summary(type="summary_text", text=summary)]
                    if summary is not None
                    else [],
                    "content": [Content(type="reasoning_text", text=text)]
                    if text is not None
                    else None,
                    "encrypted_content": encrypted_content,
                }
            ),
        )
    )
    return events


def completed(response_id: str = "resp_native", **overrides: Any) -> list[Any]:
    return [
        ResponseCompletedEvent(
            type="response.completed",
            sequence_number=99,
            response=native_response(id=response_id, status="completed", **overrides),
        )
    ]


def incomplete(reason: str, response_id: str = "resp_native") -> list[Any]:
    return [
        ResponseIncompleteEvent(
            type="response.incomplete",
            sequence_number=99,
            response=native_response(
                id=response_id, status="incomplete", incomplete_details={"reason": reason}
            ),
        )
    ]


def failed(code: str, message_text: str, response_id: str = "resp_native") -> list[Any]:
    return [
        ResponseFailedEvent(
            type="response.failed",
            sequence_number=99,
            response=native_response(
                id=response_id,
                status="failed",
                error={"code": code, "message": message_text},
            ),
        )
    ]


class ScriptedResponsesTransport:
    """Replay one list of native events per sampling request.

    ``provider`` is a constructor argument because the streams are identical for
    every provider: the same script must drive OpenAI and OpenRouter alike.
    """

    def __init__(
        self, scripts: Sequence[Sequence[Any]], *, provider: str = "openrouter"
    ) -> None:
        self.provider = provider
        self.model = "test-model"
        self._scripts = [list(script) for script in scripts]
        self.requests: list[dict[str, Any]] = []

    async def stream_response(
        self, *, input: Any, model: Any = None, **params: Any
    ) -> Any:
        self.requests.append({"input": list(input), "model": model, **params})
        events = self._scripts[len(self.requests) - 1]

        async def iterator():
            for event in events:
                yield event

        return iterator()


__all__ = [
    "ScriptedResponsesTransport",
    "completed",
    "created",
    "failed",
    "function_call",
    "incomplete",
    "message",
    "native_response",
    "reasoning",
]
