"""Turn one provider's native stream into canonical items and live events.

This is the inbound half of the protocol boundary: a provider adapter
(``openai_canonical_events``/``openrouter_canonical_events``) translates a
transport's native stream into the canonical
:class:`~bothesis.agent.protocol.ProviderStreamEvent` union, and
``StreamResponse`` is the one shared engine that turns that provider stream
into internal deltas plus a final sampling result —
regardless of which provider produced it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, cast

from openai.types.responses import Response as OpenAIResponse
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseReasoningItem,
)

from bothesis.agent import ModelStreamCompleted, TextDelta
from bothesis.agent.protocol import (
    FunctionCallItem,
    FunctionTool,
    ExtensionItem,
    IncompleteDetails,
    InputTokensDetails,
    Item,
    MessageItem,
    OutputText,
    ReasoningSummaryDelta,
    ReasoningItem,
    ReasoningSummaryText,
    Response,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseRequest,
    ResponseStatus,
    ProviderStreamEvent,
    ResponseUsage,
    Tool,
)
from bothesis.agent.transports.openai import OpenAITransport
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.agent.turn_input import ResponseItem, TurnInput


class StreamResponse:
    """Consume canonical stream events and assemble one sampling result."""

    def __init__(
        self,
        *,
        provider: Literal["openai", "openrouter"],
        sampling_number: int,
        generation_trace: Any = None,
    ) -> None:
        self._provider = provider
        self._sampling_number = sampling_number
        self._trace = generation_trace
        self._marked_first_token = False

    async def run_llm(
        self, events: AsyncIterator[ProviderStreamEvent]
    ) -> AsyncIterator[TextDelta | ReasoningSummaryDelta | ModelStreamCompleted]:
        items: list[Item] = []
        final_response: Response | None = None

        async for event in events:
            if isinstance(event, ResponseOutputTextDeltaEvent):
                self._mark_first_token()
                if event.delta:
                    yield TextDelta(text=event.delta)
            elif isinstance(event, ResponseReasoningSummaryTextDeltaEvent):
                if event.delta:
                    self._mark_first_token()
                    yield ReasoningSummaryDelta(
                        provider=self._provider,
                        sampling_number=self._sampling_number,
                        item_id=event.item_id,
                        delta=event.delta,
                    )
            elif isinstance(event, ResponseOutputItemDoneEvent):
                items.append(event.item)
            elif isinstance(
                event, (ResponseCompletedEvent, ResponseIncompleteEvent, ResponseFailedEvent)
            ):
                final_response = event.response

        if final_response is None:
            raise ValueError("provider stream ended without a completed response")
        if final_response.status == "failed":
            raise ValueError("provider response failed")

        response = final_response.model_copy(update={"output": tuple(items)})

        yield ModelStreamCompleted(
            response=response,
            duration_ms=0,  # corrected by the caller once the attempt finishes
            items=tuple(items),
        )

    def _mark_first_token(self) -> None:
        if not self._marked_first_token and self._trace is not None:
            self._trace.mark_first_token()
        self._marked_first_token = True


def _turn_input(prompt: ResponseRequest) -> TurnInput:
    """Rebuild the renderable history from a prompt's canonical item input."""

    return TurnInput(
        entries=tuple(ResponseItem(item=item) for item in prompt.input),
        instructions=prompt.instructions,
    )


async def openai_canonical_events(
    transport: OpenAITransport, prompt: ResponseRequest
) -> AsyncIterator[ProviderStreamEvent]:
    """Adapt an OpenAI Responses stream into canonical events."""

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

    async for raw in stream:
        if raw.type == "response.output_text.delta":
            yield ResponseOutputTextDeltaEvent(
                item_id=raw.item_id,
                output_index=raw.output_index,
                delta=raw.delta or "",
            )
        elif raw.type == "response.reasoning_summary_text.delta":
            yield ResponseReasoningSummaryTextDeltaEvent(
                item_id=raw.item_id,
                output_index=raw.output_index,
                summary_index=raw.summary_index,
                delta=raw.delta or "",
            )
        elif raw.type == "response.output_item.done":
            item = _openai_protocol_item(raw.item)
            if item is not None:
                yield ResponseOutputItemDoneEvent(
                    output_index=raw.output_index,
                    item=item,
                )
        elif raw.type in {"response.completed", "response.incomplete", "response.failed"}:
            response = raw.response
            protocol_response = Response(
                id=response.id,
                created_at=int(response.created_at),
                status=_openai_status(response),
                model=response.model,
                output=(),
                usage=_openai_usage(response),
                incomplete_details=_openai_incomplete_details(response),
            )
            if raw.type == "response.completed":
                yield ResponseCompletedEvent(response=protocol_response)
            elif raw.type == "response.incomplete":
                yield ResponseIncompleteEvent(response=protocol_response)
            else:
                yield ResponseFailedEvent(response=protocol_response)


async def openrouter_canonical_events(
    transport: OpenRouterTransport, prompt: ResponseRequest
) -> AsyncIterator[ProviderStreamEvent]:
    """Adapt an OpenRouter chat-completions stream into canonical events."""

    params: dict[str, Any] = dict(prompt.provider_options)
    if prompt.temperature is not None:
        params.setdefault("temperature", prompt.temperature)
    if prompt.max_output_tokens is not None:
        params.setdefault("max_tokens", prompt.max_output_tokens)
    tools = _function_tools(prompt.tools)
    if tools:
        params.setdefault("tools", _openrouter_tools(tools))
        params.setdefault("tool_choice", prompt.tool_choice or "auto")

    tool_call_deltas: dict[int, dict[str, str]] = {}
    reasoning_details: list[dict[str, Any]] = []
    legacy_reasoning_parts: list[str] = []
    finish_reason: str | None = None
    model_name: str | None = prompt.model
    usage: ResponseUsage | None = None
    annotations: list[dict[str, Any]] = []
    text_parts: list[str] = []

    async for chunk in transport.stream_chat(
        messages=cast(
            Sequence[Mapping[str, Any]],
            _turn_input(prompt).to_openrouter_messages(),
        ),
        model=prompt.model,
        **params,
    ):
        raw_model = chunk.get("model")
        if isinstance(raw_model, str) and raw_model:
            model_name = raw_model
        if "usage" in chunk:
            usage = _openrouter_usage(chunk.get("usage"))
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, Mapping):
            continue
        raw_finish_reason = choice.get("finish_reason")
        if raw_finish_reason is not None:
            finish_reason = str(raw_finish_reason)
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            continue

        content = delta.get("content")
        if isinstance(content, str) and content:
            text_parts.append(content)
            yield ResponseOutputTextDeltaEvent(
                item_id="message",
                output_index=0,
                delta=content,
            )

        raw_details = delta.get("reasoning_details")
        if isinstance(raw_details, list):
            for detail in raw_details:
                if not isinstance(detail, Mapping):
                    continue
                reasoning_details.append(dict(detail))
                if detail.get("type") == "reasoning.summary":
                    summary = detail.get("summary")
                    if isinstance(summary, str) and summary:
                        yield ResponseReasoningSummaryTextDeltaEvent(
                            item_id="reasoning",
                            output_index=0,
                            delta=summary,
                        )
        raw_reasoning = delta.get("reasoning")
        if isinstance(raw_reasoning, str) and raw_reasoning:
            # Legacy/plaintext reasoning is provider-native reasoning, not a
            # summary. Preserve it for replay but never expose it as one.
            legacy_reasoning_parts.append(raw_reasoning)

        annotations.extend(_openrouter_file_annotations(delta.get("annotations")))
        raw_calls = delta.get("tool_calls")
        if isinstance(raw_calls, list):
            _accumulate_openrouter_tool_calls(tool_call_deltas, raw_calls)

    raw_tool_calls = [
        {
            "id": pending["id"] or f"call_{index}",
            "type": "function",
            "function": {"name": pending["name"], "arguments": pending["arguments"]},
        }
        for index, pending in sorted(tool_call_deltas.items())
    ]
    function_calls = _openrouter_function_calls(raw_tool_calls)

    if reasoning_details or legacy_reasoning_parts:
        native_reasoning: dict[str, Any] = {
            "type": "openrouter.reasoning_details",
        }
        if reasoning_details:
            native_reasoning["details"] = reasoning_details
        if legacy_reasoning_parts:
            native_reasoning["reasoning"] = "".join(legacy_reasoning_parts)
        yield ResponseOutputItemDoneEvent(
            output_index=0,
            item=ExtensionItem(**native_reasoning),
        )
    if reasoning_details:
        yield ResponseOutputItemDoneEvent(
            output_index=0,
            item=ReasoningItem(
                summary=tuple(
                    ReasoningSummaryText(text=detail["summary"])
                    for detail in reasoning_details
                    if detail.get("type") == "reasoning.summary"
                    and isinstance(detail.get("summary"), str)
                ),
            ),
        )

    text = "".join(text_parts)
    if text or annotations:
        yield ResponseOutputItemDoneEvent(
            output_index=0,
            item=MessageItem(
                role="assistant",
                content=(OutputText(text=text, annotations=tuple(annotations)),),
            ),
        )
    for call in function_calls:
        yield ResponseOutputItemDoneEvent(output_index=0, item=call)

    status, incomplete_details = _status_from_finish_reason(finish_reason)
    response = Response(
        status=status,
        model=model_name,
        output=(),
        usage=usage,
        incomplete_details=incomplete_details,
    )
    if status == "completed":
        yield ResponseCompletedEvent(response=response)
    else:
        yield ResponseIncompleteEvent(response=response)


def _openai_protocol_item(item: Any) -> Item | None:
    if isinstance(item, ResponseOutputMessage):
        text = "".join(
            getattr(part, "text", "") for part in item.content if hasattr(part, "text")
        )
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
            call_id=item.call_id,
            name=item.name,
            arguments=item.arguments,
            id=item.id or None,
        )
    if isinstance(item, ResponseReasoningItem):
        summary = tuple(
            ReasoningSummaryText(text=part.text)
            for part in (item.summary or [])
            if getattr(part, "text", None)
        )
        return ReasoningItem(
            id=item.id,
            summary=summary,
            encrypted_content=item.encrypted_content,
        )
    return None


def _function_tools(tools: Sequence[Tool]) -> list[FunctionTool]:
    """Narrow the declared tools to the function tools transports understand."""

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
    if response.status in {
        "queued",
        "in_progress",
        "completed",
        "incomplete",
        "failed",
        "cancelled",
    }:
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
        input_tokens_details=InputTokensDetails(
            cached_tokens=usage.input_tokens_details.cached_tokens
        ),
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _accumulate_openrouter_tool_calls(
    pending_calls: dict[int, dict[str, str]],
    raw_calls: list[Any],
) -> None:
    for position, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, Mapping):
            continue
        raw_index = raw_call.get("index")
        index = (
            raw_index
            if isinstance(raw_index, int) and not isinstance(raw_index, bool)
            else position
        )
        pending = pending_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
        call_id = raw_call.get("id")
        if isinstance(call_id, str) and call_id:
            pending["id"] = call_id
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            continue
        name = function.get("name")
        arguments = function.get("arguments")
        if isinstance(name, str):
            pending["name"] += name
        if isinstance(arguments, str):
            pending["arguments"] += arguments


def _openrouter_usage(value: object) -> ResponseUsage | None:
    if not isinstance(value, Mapping):
        return None
    cached = 0
    prompt_details = value.get("prompt_tokens_details")
    if isinstance(prompt_details, Mapping):
        cached = _token_count(prompt_details.get("cached_tokens"))
    return ResponseUsage(
        input_tokens=_token_count(value.get("prompt_tokens")),
        input_tokens_details=InputTokensDetails(cached_tokens=cached),
        output_tokens=_token_count(value.get("completion_tokens")),
        total_tokens=_token_count(value.get("total_tokens")),
    )


def _openrouter_file_annotations(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    annotations: list[dict[str, Any]] = []
    for annotation in value:
        if not isinstance(annotation, Mapping) or annotation.get("type") != "file":
            continue
        file_value = annotation.get("file")
        if not isinstance(file_value, Mapping):
            continue
        file_hash = file_value.get("hash")
        content = file_value.get("content")
        if not isinstance(file_hash, str) or not file_hash.strip():
            continue
        if not isinstance(content, list):
            continue
        annotations.append(
            {"type": "file", "file": {str(key): item for key, item in file_value.items()}}
        )
    return annotations


def _openrouter_function_calls(raw_calls: Sequence[Mapping[str, Any]]) -> list[FunctionCallItem]:
    """Project accumulated chat-completions tool calls onto protocol items."""

    calls: list[FunctionCallItem] = []
    used_call_ids: set[str] = set()
    for index, raw_call in enumerate(raw_calls):
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        raw_call_id = raw_call.get("id")
        call_id = (
            raw_call_id.strip()
            if isinstance(raw_call_id, str) and raw_call_id.strip()
            else f"call_{index}"
        )
        if call_id in used_call_ids:
            call_id = f"{call_id}_{index}"
        used_call_ids.add(call_id)
        raw_arguments = function.get("arguments")
        calls.append(
            FunctionCallItem(
                call_id=call_id,
                name=name.strip(),
                arguments=(
                    raw_arguments
                    if isinstance(raw_arguments, str)
                    else json.dumps(raw_arguments, ensure_ascii=False)
                    if isinstance(raw_arguments, Mapping)
                    else ""
                ),
            )
        )
    return calls


def _status_from_finish_reason(
    finish_reason: str | None,
) -> tuple[ResponseStatus, IncompleteDetails | None]:
    if finish_reason in (None, "stop", "tool_calls", "function_call"):
        return "completed", None
    if finish_reason == "length":
        return "incomplete", IncompleteDetails(reason="max_output_tokens")
    return "incomplete", IncompleteDetails(reason=finish_reason)


def _token_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


__all__ = [
    "StreamResponse",
    "openai_canonical_events",
    "openrouter_canonical_events",
]
