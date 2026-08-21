"""Provider adapters and materialization for one sampling response.

Transports only expose native provider streams.  The adapters in this module
translate them into the compact BoThesis response protocol, while
``StreamResponse`` applies enterprise-only citation annotations and assembles
the immutable response used by the Turn loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, cast
from uuid import uuid4

from openai.types.responses import Response as OpenAIResponse
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseReasoningItem,
)

from bothesis.agent import ModelStreamCompleted
from bothesis.agent.citation import CitationRenderer
from bothesis.agent.models import Evidence
from bothesis.agent.protocol import (
    ExtensionItem,
    FunctionCallItem,
    FunctionTool,
    IncompleteDetails,
    InputTokensDetails,
    Item,
    MessageItem,
    OutputText,
    ReasoningItem,
    ReasoningSummaryText,
    Response,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseRequest,
    ResponseStatus,
    ResponseStreamEvent,
    ResponseUsage,
    Tool,
)
from bothesis.agent.transports.openai import OpenAITransport
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.agent.turn_input import ResponseItem, TurnInput


class StreamResponse:
    """Materialize one response and project citation markers into annotations."""

    def __init__(
        self,
        *,
        generation_trace: Any = None,
        evidence: Mapping[str, Evidence],
    ) -> None:
        self._trace = generation_trace
        self._evidence = evidence
        self._marked_first_token = False
        self._renderers: dict[str, CitationRenderer] = {}
        self._text: dict[str, list[str]] = {}
        self._annotations: dict[str, list[dict[str, object]]] = {}
        self._used_evidence_ids: set[str] = set()

    async def run_llm(
        self, events: AsyncIterator[ResponseStreamEvent]
    ) -> AsyncIterator[ResponseStreamEvent | ModelStreamCompleted]:
        """Forward semantic events and finish with the materialized response."""

        items_by_index: dict[int, Item] = {}
        final_response: Response | None = None

        async for event in events:
            for projected in self._project(event):
                if isinstance(projected, ResponseOutputTextDeltaEvent) and projected.delta:
                    self._mark_first_token()
                if isinstance(projected, ResponseOutputItemDoneEvent):
                    items_by_index[projected.output_index] = projected.item
                if isinstance(
                    projected,
                    (ResponseCompletedEvent, ResponseIncompleteEvent, ResponseFailedEvent),
                ):
                    response = projected.response.model_copy(
                        update={
                            "output": tuple(
                                item for _, item in sorted(items_by_index.items())
                            )
                        }
                    )
                    projected = projected.model_copy(update={"response": response})
                    final_response = response
                yield projected

        if final_response is None:
            raise ValueError("provider stream ended without a terminal response")
        if final_response.status == "failed":
            raise ValueError("provider response failed")
        yield ModelStreamCompleted(
            response=final_response,
            duration_ms=0,
            items=final_response.output,
            used_evidence_ids=frozenset(self._used_evidence_ids),
        )

    def _project(self, event: ResponseStreamEvent) -> tuple[ResponseStreamEvent, ...]:
        if isinstance(event, ResponseOutputTextDeltaEvent):
            return self._text_delta_events(event)
        if isinstance(event, ResponseOutputTextDoneEvent):
            events = list(self._flush_text(event))
            events.append(
                event.model_copy(update={"text": self._text_value(event.item_id)})
            )
            return tuple(events)
        if (
            isinstance(event, ResponseContentPartDoneEvent)
            and isinstance(event.part, OutputText)
            and event.item_id in self._text
        ):
            return (
                event.model_copy(
                    update={
                        "part": OutputText(
                            text=self._text_value(event.item_id),
                            annotations=tuple(
                                [
                                    *event.part.annotations,
                                    *self._annotations.get(event.item_id, ()),
                                ]
                            ),
                        )
                    }
                ),
            )
        if isinstance(event, ResponseOutputItemDoneEvent) and isinstance(
            event.item, MessageItem
        ):
            return (event.model_copy(update={"item": self._message_item(event.item)}),)
        return (event,)

    def _text_delta_events(
        self, event: ResponseOutputTextDeltaEvent
    ) -> tuple[ResponseStreamEvent, ...]:
        self._mark_text_item(event.item_id)
        if not self._evidence:
            self._text[event.item_id].append(event.delta)
            return (event,)

        events: list[ResponseStreamEvent] = []
        renderer = self._renderers.setdefault(event.item_id, CitationRenderer())
        for visible_text, evidence_id in renderer.push(
            event.delta, self._evidence, self._used_evidence_ids
        ):
            if visible_text:
                self._text[event.item_id].append(visible_text)
                events.append(event.model_copy(update={"delta": visible_text}))
            if evidence_id:
                annotation = self._citation_annotation(
                    evidence_id, len(self._text_value(event.item_id))
                )
                self._annotations[event.item_id].append(annotation)
                events.append(
                    ResponseOutputTextAnnotationAddedEvent(
                        response_id=event.response_id,
                        item_id=event.item_id,
                        output_index=event.output_index,
                        content_index=event.content_index,
                        annotation=annotation,
                    )
                )
        return tuple(events)

    def _flush_text(
        self, event: ResponseOutputTextDoneEvent
    ) -> tuple[ResponseStreamEvent, ...]:
        renderer = self._renderers.get(event.item_id)
        if renderer is None:
            return ()
        trailing = renderer.flush()
        if trailing is None or not trailing[0]:
            return ()
        self._text[event.item_id].append(trailing[0])
        return (ResponseOutputTextDeltaEvent(
            response_id=event.response_id,
            item_id=event.item_id,
            output_index=event.output_index,
            content_index=event.content_index,
            delta=trailing[0],
        ),)

    def _message_item(self, item: MessageItem) -> MessageItem:
        if item.id is None or item.id not in self._text:
            return item
        annotations = list(self._annotations.get(item.id, ()))
        content = tuple(
            OutputText(
                text=self._text_value(item.id),
                annotations=tuple(
                    [*part.annotations, *annotations]
                    if isinstance(part, OutputText)
                    else []
                ),
            )
            if isinstance(part, OutputText)
            else part
            for part in item.content
        )
        return item.model_copy(update={"content": content, "status": "completed"})

    def _citation_annotation(self, evidence_id: str, offset: int) -> dict[str, object]:
        evidence = self._evidence[evidence_id]
        annotation: dict[str, object] = {
            "type": "citation",
            "start_index": offset,
            "end_index": offset,
            "citation": {
                "id": evidence.id,
                "document_id": evidence.document_id,
                "title": evidence.title,
                "page": evidence.page,
                "section": evidence.section,
                "uri": evidence.uri,
                "source": evidence.source,
            },
        }
        return annotation

    def _mark_text_item(self, item_id: str) -> None:
        self._text.setdefault(item_id, [])
        self._annotations.setdefault(item_id, [])

    def _text_value(self, item_id: str) -> str:
        return "".join(self._text.get(item_id, ()))

    def _mark_first_token(self) -> None:
        if not self._marked_first_token and self._trace is not None:
            self._trace.mark_first_token()
        self._marked_first_token = True


def _turn_input(prompt: ResponseRequest) -> TurnInput:
    return TurnInput(
        entries=tuple(ResponseItem(item=item) for item in prompt.input),
        instructions=prompt.instructions,
    )


async def openai_canonical_events(
    transport: OpenAITransport, prompt: ResponseRequest
) -> AsyncIterator[ResponseStreamEvent]:
    """Map native OpenAI Responses events to the BoThesis public protocol."""

    params: dict[str, Any] = dict(prompt.provider_options)
    if prompt.instructions is not None:
        params.setdefault("instructions", prompt.instructions)
    if prompt.temperature is not None:
        params.setdefault("temperature", prompt.temperature)
    if prompt.max_output_tokens is not None:
        params.setdefault("max_output_tokens", prompt.max_output_tokens)
    tools = _function_tools(prompt.tools)
    if tools:
        params.setdefault("tools", _openai_tools(tools))
        params.setdefault("tool_choice", prompt.tool_choice or "auto")
    if prompt.parallel_tool_calls is not None:
        params.setdefault("parallel_tool_calls", prompt.parallel_tool_calls)

    stream = await transport.stream_response(
        input=cast(Any, _turn_input(prompt).to_openai_input()),
        model=prompt.model,
        **params,
    )
    response_id: str | None = None

    async for raw in stream:
        raw_response = getattr(raw, "response", None)
        if raw.type == "response.created" and raw_response is not None:
            if response_id is None:
                response_id = raw_response.id
                yield ResponseCreatedEvent(
                    response_id=response_id,
                    response=_openai_response(raw_response, response_id, status="in_progress"),
                )
            continue
        if response_id is None:
            response_id = f"resp_{uuid4().hex}"
            yield ResponseCreatedEvent(
                response_id=response_id,
                response=Response(id=response_id, status="in_progress", model=prompt.model),
            )

        if raw.type == "response.output_item.added":
            item = _openai_protocol_item(raw.item)
            if item is not None:
                yield ResponseOutputItemAddedEvent(
                    response_id=response_id,
                    output_index=raw.output_index,
                    item=_item_with_id(item, _item_id(response_id, raw.output_index)),
                )
        elif raw.type == "response.content_part.added":
            part = _openai_content_part(raw.part)
            if part is not None:
                yield ResponseContentPartAddedEvent(
                    response_id=response_id,
                    item_id=raw.item_id,
                    output_index=raw.output_index,
                    content_index=raw.content_index,
                    part=part,
                )
        elif raw.type == "response.output_text.delta":
            yield ResponseOutputTextDeltaEvent(
                response_id=response_id,
                item_id=raw.item_id,
                output_index=raw.output_index,
                content_index=raw.content_index,
                delta=raw.delta or "",
            )
        elif raw.type == "response.output_text.done":
            yield ResponseOutputTextDoneEvent(
                response_id=response_id,
                item_id=raw.item_id,
                output_index=raw.output_index,
                content_index=raw.content_index,
                text=raw.text or "",
            )
        elif raw.type == "response.content_part.done":
            part = _openai_content_part(raw.part)
            if part is not None:
                yield ResponseContentPartDoneEvent(
                    response_id=response_id,
                    item_id=raw.item_id,
                    output_index=raw.output_index,
                    content_index=raw.content_index,
                    part=part,
                )
        elif raw.type == "response.function_call_arguments.delta":
            yield ResponseFunctionCallArgumentsDeltaEvent(
                response_id=response_id,
                item_id=raw.item_id,
                output_index=raw.output_index,
                delta=raw.delta or "",
            )
        elif raw.type == "response.function_call_arguments.done":
            yield ResponseFunctionCallArgumentsDoneEvent(
                response_id=response_id,
                item_id=raw.item_id,
                output_index=raw.output_index,
                arguments=raw.arguments or "",
            )
        elif raw.type == "response.output_text.annotation.added":
            yield ResponseOutputTextAnnotationAddedEvent(
                response_id=response_id,
                item_id=raw.item_id,
                output_index=raw.output_index,
                content_index=raw.content_index,
                annotation=raw.annotation.model_dump(mode="json"),
            )
        elif raw.type == "response.output_item.done":
            item = _openai_protocol_item(raw.item)
            if item is not None:
                yield ResponseOutputItemDoneEvent(
                    response_id=response_id,
                    output_index=raw.output_index,
                    item=_item_with_id(item, _item_id(response_id, raw.output_index)),
                )
        elif raw.type in {"response.completed", "response.incomplete", "response.failed"}:
            response = _openai_response(raw.response, response_id)
            if raw.type == "response.completed":
                yield ResponseCompletedEvent(response=response)
            elif raw.type == "response.incomplete":
                yield ResponseIncompleteEvent(response=response)
            else:
                yield ResponseFailedEvent(response=response)


async def openrouter_canonical_events(
    transport: OpenRouterTransport, prompt: ResponseRequest
) -> AsyncIterator[ResponseStreamEvent]:
    """Map OpenRouter chat-completions chunks to response/item lifecycles."""

    params: dict[str, Any] = dict(prompt.provider_options)
    if prompt.temperature is not None:
        params.setdefault("temperature", prompt.temperature)
    if prompt.max_output_tokens is not None:
        params.setdefault("max_tokens", prompt.max_output_tokens)
    tools = _function_tools(prompt.tools)
    if tools:
        params.setdefault("tools", _openrouter_tools(tools))
        params.setdefault("tool_choice", prompt.tool_choice or "auto")

    response_id = f"resp_{uuid4().hex}"
    yield ResponseCreatedEvent(
        response_id=response_id,
        response=Response(id=response_id, status="in_progress", model=prompt.model),
    )
    message_id = _item_id(response_id, 0)
    message_started = False
    text_parts: list[str] = []
    annotations: list[dict[str, object]] = []
    tool_calls: dict[int, dict[str, object]] = {}
    finish_reason: str | None = None
    model_name = prompt.model
    usage: ResponseUsage | None = None
    reasoning_details: list[dict[str, Any]] = []
    legacy_reasoning_parts: list[str] = []

    async for chunk in transport.stream_chat(
        messages=cast(Sequence[Mapping[str, Any]], _turn_input(prompt).to_openrouter_messages()),
        model=prompt.model,
        **params,
    ):
        if isinstance(chunk.get("model"), str) and chunk["model"]:
            model_name = str(chunk["model"])
        if "usage" in chunk:
            usage = _openrouter_usage(chunk.get("usage"))
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            continue
        choice = choices[0]
        if choice.get("finish_reason") is not None:
            finish_reason = str(choice["finish_reason"])
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            continue

        content = delta.get("content")
        if isinstance(content, str) and content:
            if not message_started:
                message_started = True
                yield ResponseOutputItemAddedEvent(
                    response_id=response_id,
                    output_index=0,
                    item=MessageItem(
                        id=message_id,
                        role="assistant",
                        content=(OutputText(text=""),),
                        status="in_progress",
                    ),
                )
                yield ResponseContentPartAddedEvent(
                    response_id=response_id,
                    item_id=message_id,
                    output_index=0,
                    content_index=0,
                    part=OutputText(text=""),
                )
            text_parts.append(content)
            yield ResponseOutputTextDeltaEvent(
                response_id=response_id,
                item_id=message_id,
                output_index=0,
                content_index=0,
                delta=content,
            )

        for annotation in _openrouter_file_annotations(delta.get("annotations")):
            annotations.append(annotation)
            if message_started:
                yield ResponseOutputTextAnnotationAddedEvent(
                    response_id=response_id,
                    item_id=message_id,
                    output_index=0,
                    content_index=0,
                    annotation=annotation,
                )
        raw_details = delta.get("reasoning_details")
        if isinstance(raw_details, list):
            reasoning_details.extend(dict(detail) for detail in raw_details if isinstance(detail, Mapping))
        raw_reasoning = delta.get("reasoning")
        if isinstance(raw_reasoning, str) and raw_reasoning:
            legacy_reasoning_parts.append(raw_reasoning)

        raw_calls = delta.get("tool_calls")
        if isinstance(raw_calls, list):
            for event in _openrouter_tool_call_events(response_id, tool_calls, raw_calls):
                yield event

    if message_started:
        raw_text = "".join(text_parts)
        yield ResponseOutputTextDoneEvent(
            response_id=response_id,
            item_id=message_id,
            output_index=0,
            content_index=0,
            text=raw_text,
        )
        part = OutputText(text=raw_text, annotations=tuple(annotations))
        yield ResponseContentPartDoneEvent(
            response_id=response_id,
            item_id=message_id,
            output_index=0,
            content_index=0,
            part=part,
        )
        yield ResponseOutputItemDoneEvent(
            response_id=response_id,
            output_index=0,
            item=MessageItem(
                id=message_id, role="assistant", content=(part,), status="completed"
            ),
        )

    next_output_index = max(
        (int(pending["output_index"]) + 1 for pending in tool_calls.values()),
        default=1 if message_started else 0,
    )
    if reasoning_details or legacy_reasoning_parts:
        native: dict[str, Any] = {"type": "openrouter.reasoning_details"}
        if reasoning_details:
            native["details"] = reasoning_details
        if legacy_reasoning_parts:
            native["reasoning"] = "".join(legacy_reasoning_parts)
        item = ExtensionItem(id=_item_id(response_id, next_output_index), **native)
        yield ResponseOutputItemAddedEvent(
            response_id=response_id, output_index=next_output_index, item=item
        )
        yield ResponseOutputItemDoneEvent(
            response_id=response_id, output_index=next_output_index, item=item
        )
        next_output_index += 1

    for _, pending in sorted(tool_calls.items()):
        item_id = str(pending["item_id"])
        output_index = int(pending["output_index"])
        call = FunctionCallItem(
            id=item_id,
            call_id=str(pending["call_id"]),
            name=str(pending["name"]),
            arguments=str(pending["arguments"]),
            status="completed",
        )
        if not pending["added"]:
            yield ResponseOutputItemAddedEvent(
                response_id=response_id, output_index=output_index, item=call.model_copy(
                    update={"status": "in_progress"}
                )
            )
        yield ResponseFunctionCallArgumentsDoneEvent(
            response_id=response_id,
            item_id=item_id,
            output_index=output_index,
            arguments=call.arguments,
        )
        yield ResponseOutputItemDoneEvent(
            response_id=response_id, output_index=output_index, item=call
        )

    status, incomplete_details = _status_from_finish_reason(finish_reason)
    response = Response(
        id=response_id,
        status=status,
        model=model_name,
        usage=usage,
        incomplete_details=incomplete_details,
    )
    if status == "completed":
        yield ResponseCompletedEvent(response=response)
    else:
        yield ResponseIncompleteEvent(response=response)


def _openrouter_tool_call_events(
    response_id: str,
    pending_calls: dict[int, dict[str, object]],
    raw_calls: list[Any],
) -> tuple[ResponseStreamEvent, ...]:
    events: list[ResponseStreamEvent] = []
    for position, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, Mapping):
            continue
        raw_index = raw_call.get("index")
        index = raw_index if isinstance(raw_index, int) and not isinstance(raw_index, bool) else position
        pending = pending_calls.setdefault(
            index,
            {
                "call_id": f"call_{index}",
                "name": "",
                "arguments": "",
                "item_id": _item_id(response_id, index + 1),
                "output_index": index + 1,
                "added": False,
            },
        )
        call_id = raw_call.get("id")
        if isinstance(call_id, str) and call_id:
            pending["call_id"] = call_id
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            continue
        name = function.get("name")
        if isinstance(name, str):
            pending["name"] = f"{pending['name']}{name}"
        arguments = function.get("arguments")
        argument_delta = arguments if isinstance(arguments, str) else ""
        if argument_delta:
            pending["arguments"] = f"{pending['arguments']}{argument_delta}"
        if pending["name"] and not pending["added"]:
            pending["added"] = True
            events.append(
                ResponseOutputItemAddedEvent(
                    response_id=response_id,
                    output_index=int(pending["output_index"]),
                    item=FunctionCallItem(
                        id=str(pending["item_id"]),
                        call_id=str(pending["call_id"]),
                        name=str(pending["name"]),
                        arguments="",
                        status="in_progress",
                    ),
                )
            )
        if argument_delta and pending["added"]:
            events.append(
                ResponseFunctionCallArgumentsDeltaEvent(
                    response_id=response_id,
                    item_id=str(pending["item_id"]),
                    output_index=int(pending["output_index"]),
                    delta=argument_delta,
                )
            )
    return tuple(events)


def _openai_response(
    response: OpenAIResponse, response_id: str, *, status: ResponseStatus | None = None
) -> Response:
    return Response(
        id=response_id,
        created_at=int(response.created_at),
        status=status or _openai_status(response),
        model=response.model,
        usage=_openai_usage(response),
        incomplete_details=_openai_incomplete_details(response),
    )


def _openai_protocol_item(item: Any) -> Item | None:
    if isinstance(item, ResponseOutputMessage):
        text = "".join(getattr(part, "text", "") for part in item.content if hasattr(part, "text"))
        annotations = [
            annotation.model_dump(mode="json")
            for part in item.content
            for annotation in getattr(part, "annotations", [])
        ]
        return MessageItem(
            role="assistant",
            content=(OutputText(text=text, annotations=tuple(annotations)),),
            id=item.id,
        )
    if isinstance(item, ResponseFunctionToolCall):
        return FunctionCallItem(
            call_id=item.call_id, name=item.name, arguments=item.arguments, id=item.id or None
        )
    if isinstance(item, ResponseReasoningItem):
        summary = tuple(
            ReasoningSummaryText(text=part.text)
            for part in (item.summary or [])
            if getattr(part, "text", None)
        )
        return ReasoningItem(
            id=item.id, summary=summary, encrypted_content=item.encrypted_content
        )
    return None


def _openai_content_part(part: Any) -> OutputText | None:
    if getattr(part, "type", None) == "output_text":
        return OutputText(
            text=getattr(part, "text", "") or "",
            annotations=tuple(
                annotation.model_dump(mode="json")
                for annotation in getattr(part, "annotations", [])
            ),
        )
    return None


def _item_with_id(item: Item, fallback_id: str) -> Item:
    if getattr(item, "id", None):
        return item
    return item.model_copy(update={"id": fallback_id})


def _item_id(response_id: str, output_index: int) -> str:
    return f"{response_id}:output:{output_index}"


def _function_tools(tools: Sequence[Tool]) -> list[FunctionTool]:
    return [tool for tool in tools if isinstance(tool, FunctionTool)]


def _openai_tools(tools: Sequence[FunctionTool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "strict": tool.strict,
        }
        for tool in tools
    ]


def _openrouter_tools(tools: Sequence[FunctionTool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


def _openai_status(response: OpenAIResponse) -> ResponseStatus:
    if response.status in {"queued", "in_progress", "completed", "incomplete", "failed", "cancelled"}:
        return cast(ResponseStatus, response.status)
    return "completed"


def _openai_incomplete_details(response: OpenAIResponse) -> IncompleteDetails | None:
    incomplete = response.incomplete_details
    if incomplete is None or incomplete.reason is None:
        return None
    return IncompleteDetails(reason=incomplete.reason)


def _openai_usage(response: OpenAIResponse) -> ResponseUsage | None:
    usage = response.usage
    if usage is None:
        return None
    return ResponseUsage(
        input_tokens=usage.input_tokens,
        input_tokens_details=InputTokensDetails(cached_tokens=usage.input_tokens_details.cached_tokens),
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _openrouter_file_annotations(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    annotations: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or item.get("type") != "file":
            continue
        file_value = item.get("file")
        if isinstance(file_value, Mapping):
            annotations.append({"type": "file", "file": dict(file_value)})
    return annotations


def _openrouter_usage(value: object) -> ResponseUsage | None:
    if not isinstance(value, Mapping):
        return None
    prompt = _token_count(value.get("prompt_tokens"))
    completion = _token_count(value.get("completion_tokens"))
    total = _token_count(value.get("total_tokens"))
    return ResponseUsage(input_tokens=prompt, output_tokens=completion, total_tokens=total or prompt + completion)


def _status_from_finish_reason(
    finish_reason: str | None,
) -> tuple[ResponseStatus, IncompleteDetails | None]:
    if finish_reason in (None, "stop", "tool_calls", "function_call"):
        return "completed", None
    if finish_reason == "length":
        return "incomplete", IncompleteDetails(reason="max_output_tokens")
    return "incomplete", IncompleteDetails(reason=finish_reason)


def _token_count(value: object) -> int:
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = ["StreamResponse", "openai_canonical_events", "openrouter_canonical_events"]
