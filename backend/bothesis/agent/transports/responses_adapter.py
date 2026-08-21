from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from openai.types.responses import Response as NativeResponse

from bothesis.agent.protocol import (
    CompactionItem,
    ContentPart,
    ErrorEvent,
    ErrorPayload,
    ExtensionItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    FunctionTool,
    IncompleteDetails,
    InputFile,
    InputImage,
    InputText,
    InputTokensDetails,
    Item,
    MessageItem,
    OutputText,
    OutputTokensDetails,
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
    ResponseInProgressEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseQueuedEvent,
    ResponseReasoningDeltaEvent,
    ResponseReasoningDoneEvent,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryPartDoneEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    ResponseRefusalDeltaEvent,
    ResponseRefusalDoneEvent,
    ResponseRequest,
    ResponseStatus,
    ResponseStreamEvent,
    ResponseUsage,
    SummaryText,
    Tool,
)

_RESPONSE_STATUSES = frozenset(
    {"queued", "in_progress", "completed", "incomplete", "failed", "cancelled"}
)


class ResponsesStream:
    """Expose one native ``/responses`` transport through the canonical contract."""

    def __init__(self, transport: Any) -> None:
        self._transport = transport

    @property
    def provider(self) -> str:
        return getattr(self._transport, "provider", "")

    @property
    def model(self) -> str | None:
        return getattr(self._transport, "model", None)

    async def stream(
        self, request: ResponseRequest
    ) -> AsyncIterator[ResponseStreamEvent]:
        """Yield one canonical event per native event, without buffering."""

        stream = await self._transport.stream_response(
            input=cast(Any, render_input(request.input)),
            model=request.model,
            **_native_params(request),
        )
        async for native in stream:
            for event in _project(native, request):
                yield event


def render_input(items: Sequence[Item]) -> list[dict[str, Any]]:
    """Render canonical items as OpenAI Responses input items.

    Annotations are dropped: OpenAI only accepts ``url_citation`` on replayed
    output text, and BoThesis document citations are its own annotation type.
    """

    rendered: list[dict[str, Any]] = []
    for item in items:
        block = _input_item(item)
        if block is not None:
            rendered.append(block)
    return rendered


def _native_params(request: ResponseRequest) -> dict[str, Any]:
    """Render the specified request fields as native ``/responses`` parameters.

    ``provider_options`` is not merged here: it holds keys outside the
    specification (routing preferences, plugins, sampling knobs a single
    provider offers) and is handed to the transport as ``extra_body``, which
    merges it into the request body without this module naming any of it.
    """

    params: dict[str, Any] = {}
    if request.instructions is not None:
        params["instructions"] = request.instructions
    if request.temperature is not None:
        params["temperature"] = request.temperature
    if request.top_p is not None:
        params["top_p"] = request.top_p
    if request.max_output_tokens is not None:
        params["max_output_tokens"] = request.max_output_tokens
    if request.max_tool_calls is not None:
        params["max_tool_calls"] = request.max_tool_calls
    if request.store is not None:
        params["store"] = request.store
    if request.metadata:
        params["metadata"] = dict(request.metadata)
    tools = _function_tools(request.tools)
    if tools:
        params["tools"] = _native_tools(tools)
        params["tool_choice"] = _native_tool_choice(request)
    if request.parallel_tool_calls is not None:
        params["parallel_tool_calls"] = request.parallel_tool_calls
    if request.provider_options:
        params["extra_body"] = dict(request.provider_options)
    return params


def _function_tools(tools: Sequence[Tool]) -> list[FunctionTool]:
    return [tool for tool in tools if isinstance(tool, FunctionTool)]


def _native_tools(tools: Sequence[FunctionTool]) -> list[dict[str, Any]]:
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


def _native_tool_choice(request: ResponseRequest) -> Any:
    choice = request.tool_choice
    if choice is None:
        return "auto"
    if isinstance(choice, str):
        return choice
    return choice.model_dump(mode="json")


def _input_item(item: Item) -> dict[str, Any] | None:
    if isinstance(item, MessageItem):
        block: dict[str, Any] = {
            "type": "message",
            "role": item.role,
            "content": _input_content(item),
        }
        if item.role == "assistant" and item.phase is not None:
            block["phase"] = item.phase
        return block
    if isinstance(item, ReasoningItem):
        # ``ReasoningItemParam`` accepts summary and encrypted content only.
        block = {
            "type": "reasoning",
            "summary": [
                {"type": "summary_text", "text": part.text} for part in item.summary
            ],
        }
        if item.id is not None:
            block["id"] = item.id
        if item.encrypted_content is not None:
            block["encrypted_content"] = item.encrypted_content
        return block
    if isinstance(item, FunctionCallItem):
        block = {
            "type": "function_call",
            "call_id": item.call_id,
            "name": item.name,
            "arguments": item.arguments,
        }
        if item.id is not None:
            block["id"] = item.id
        return block
    if isinstance(item, FunctionCallOutputItem):
        return {
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": item.output,
        }
    if isinstance(item, CompactionItem):
        block = {"type": "compaction", "encrypted_content": item.encrypted_content}
        if item.id is not None:
            block["id"] = item.id
        return block
    if isinstance(item, ExtensionItem):
        return item.model_dump(mode="json", exclude_none=True)
    return None


def _input_content(item: MessageItem) -> str | list[dict[str, Any]]:
    if len(item.content) == 1 and isinstance(item.content[0], (InputText, OutputText)):
        return item.content[0].text
    blocks: list[dict[str, Any]] = []
    for part in item.content:
        if isinstance(part, InputText):
            blocks.append({"type": "input_text", "text": part.text})
        elif isinstance(part, OutputText):
            blocks.append({"type": "output_text", "text": part.text})
        elif isinstance(part, Refusal):
            blocks.append({"type": "refusal", "refusal": part.refusal})
        elif isinstance(part, InputImage):
            block: dict[str, Any] = {"type": "input_image", "detail": part.detail}
            if part.image_url is not None:
                block["image_url"] = part.image_url
            if part.file_id is not None:
                block["file_id"] = part.file_id
            blocks.append(block)
        elif isinstance(part, InputFile):
            block = {"type": "input_file"}
            for key in ("file_id", "file_url", "filename", "file_data"):
                value = getattr(part, key)
                if value is not None:
                    block[key] = value
            blocks.append(block)
    return blocks


def _project(
    native: Any, request: ResponseRequest
) -> tuple[ResponseStreamEvent, ...]:
    """Map one native event onto zero or one canonical events."""

    kind = getattr(native, "type", None)
    if kind == "response.created":
        return (
            ResponseCreatedEvent(
                response=_response(native.response, request, status="in_progress")
            ),
        )
    if kind == "response.queued":
        return (
            ResponseQueuedEvent(
                response=_response(native.response, request, status="queued")
            ),
        )
    if kind == "response.in_progress":
        return (
            ResponseInProgressEvent(
                response=_response(native.response, request, status="in_progress")
            ),
        )
    if kind == "response.completed":
        return (ResponseCompletedEvent(response=_response(native.response, request)),)
    if kind == "response.incomplete":
        return (ResponseIncompleteEvent(response=_response(native.response, request)),)
    if kind == "response.failed":
        return (ResponseFailedEvent(response=_response(native.response, request)),)
    if kind == "error":
        return (
            ErrorEvent(
                error=ErrorPayload(
                    message=native.message or "provider stream error",
                    code=native.code,
                    param=native.param,
                )
            ),
        )
    if kind == "response.output_item.added":
        item = _item(native.item)
        return (
            (
                ResponseOutputItemAddedEvent(
                    output_index=native.output_index, item=item
                ),
            )
            if item is not None
            else ()
        )
    if kind == "response.output_item.done":
        item = _item(native.item)
        return (
            (ResponseOutputItemDoneEvent(output_index=native.output_index, item=item),)
            if item is not None
            else ()
        )
    if kind == "response.content_part.added":
        part = _content_part(native.part)
        return (
            (
                ResponseContentPartAddedEvent(
                    item_id=native.item_id,
                    output_index=native.output_index,
                    content_index=native.content_index,
                    part=part,
                ),
            )
            if part is not None
            else ()
        )
    if kind == "response.content_part.done":
        part = _content_part(native.part)
        return (
            (
                ResponseContentPartDoneEvent(
                    item_id=native.item_id,
                    output_index=native.output_index,
                    content_index=native.content_index,
                    part=part,
                ),
            )
            if part is not None
            else ()
        )
    if kind == "response.output_text.delta":
        return (
            ResponseOutputTextDeltaEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                content_index=native.content_index,
                delta=native.delta or "",
            ),
        )
    if kind == "response.output_text.done":
        return (
            ResponseOutputTextDoneEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                content_index=native.content_index,
                text=native.text or "",
            ),
        )
    if kind == "response.output_text.annotation.added":
        return (
            ResponseOutputTextAnnotationAddedEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                content_index=native.content_index,
                annotation_index=native.annotation_index,
                annotation=_annotation(native.annotation),
            ),
        )
    if kind == "response.refusal.delta":
        return (
            ResponseRefusalDeltaEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                content_index=native.content_index,
                delta=native.delta or "",
            ),
        )
    if kind == "response.refusal.done":
        return (
            ResponseRefusalDoneEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                content_index=native.content_index,
                refusal=native.refusal or "",
            ),
        )
    if kind == "response.reasoning_text.delta":
        return (
            ResponseReasoningDeltaEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                content_index=native.content_index,
                delta=native.delta or "",
            ),
        )
    if kind == "response.reasoning_text.done":
        return (
            ResponseReasoningDoneEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                content_index=native.content_index,
                text=native.text or "",
            ),
        )
    if kind == "response.reasoning_summary_part.added":
        return (
            ResponseReasoningSummaryPartAddedEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                summary_index=native.summary_index,
                part=SummaryText(text=getattr(native.part, "text", "") or ""),
            ),
        )
    if kind == "response.reasoning_summary_part.done":
        return (
            ResponseReasoningSummaryPartDoneEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                summary_index=native.summary_index,
                part=SummaryText(text=getattr(native.part, "text", "") or ""),
            ),
        )
    if kind == "response.reasoning_summary_text.delta":
        return (
            ResponseReasoningSummaryTextDeltaEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                summary_index=native.summary_index,
                delta=native.delta or "",
            ),
        )
    if kind == "response.reasoning_summary_text.done":
        return (
            ResponseReasoningSummaryTextDoneEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                summary_index=native.summary_index,
                text=native.text or "",
            ),
        )
    if kind == "response.function_call_arguments.delta":
        return (
            ResponseFunctionCallArgumentsDeltaEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                delta=native.delta or "",
            ),
        )
    if kind == "response.function_call_arguments.done":
        return (
            ResponseFunctionCallArgumentsDoneEvent(
                item_id=native.item_id,
                output_index=native.output_index,
                arguments=native.arguments or "",
            ),
        )
    # Hosted-tool and audio lifecycles BoThesis never declares.
    return ()


def _response(
    native: NativeResponse,
    request: ResponseRequest,
    *,
    status: ResponseStatus | None = None,
) -> Response:
    return Response(
        id=native.id,
        status=status or _status(native),
        created_at=int(native.created_at),
        completed_at=_optional_int(getattr(native, "completed_at", None)),
        model=native.model,
        previous_response_id=request.previous_response_id,
        output=tuple(
            item for item in (_item(entry) for entry in native.output) if item is not None
        ),
        usage=_usage(native),
        error=_error(native),
        incomplete_details=_incomplete_details(native),
    )


def _status(native: NativeResponse) -> ResponseStatus:
    if native.status in _RESPONSE_STATUSES:
        return cast(ResponseStatus, native.status)
    return "completed"


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _error(native: NativeResponse) -> ResponseError | None:
    error = native.error
    if error is None:
        return None
    return ResponseError(code=error.code or "provider_error", message=error.message)


def _incomplete_details(native: NativeResponse) -> IncompleteDetails | None:
    incomplete = native.incomplete_details
    if incomplete is None or incomplete.reason is None:
        return None
    return IncompleteDetails(reason=incomplete.reason)


def _usage(native: NativeResponse) -> ResponseUsage | None:
    usage = native.usage
    if usage is None:
        return None
    return ResponseUsage(
        input_tokens=usage.input_tokens,
        input_tokens_details=InputTokensDetails(
            cached_tokens=usage.input_tokens_details.cached_tokens
        ),
        output_tokens=usage.output_tokens,
        output_tokens_details=OutputTokensDetails(
            reasoning_tokens=usage.output_tokens_details.reasoning_tokens
        ),
        total_tokens=usage.total_tokens,
    )


def _item(native: Any) -> Item | None:
    """Map one native output item, discriminated by ``type`` as specified."""

    kind = getattr(native, "type", None)
    if kind == "message":
        return MessageItem(
            id=native.id,
            role="assistant",
            status=native.status,
            phase=getattr(native, "phase", None),
            content=tuple(
                part
                for part in (_content_part(entry) for entry in native.content)
                if part is not None
            ),
        )
    if kind == "function_call":
        return FunctionCallItem(
            id=native.id or None,
            call_id=native.call_id,
            name=native.name,
            arguments=native.arguments or "",
            status=native.status,
        )
    if kind == "reasoning":
        return ReasoningItem(
            id=native.id,
            status=native.status,
            content=tuple(
                ReasoningText(text=part.text) for part in (native.content or [])
            ),
            summary=tuple(SummaryText(text=part.text) for part in (native.summary or [])),
            encrypted_content=native.encrypted_content,
        )
    payload = _dump(native)
    if payload is None or not isinstance(payload.get("type"), str):
        return None
    if kind == "compaction":
        return CompactionItem(
            id=payload.get("id"),
            encrypted_content=payload.get("encrypted_content", ""),
            created_by=payload.get("created_by"),
        )
    if kind == "function_call_output":
        return FunctionCallOutputItem(
            id=payload.get("id"),
            call_id=payload.get("call_id", ""),
            output=payload.get("output", ""),
        )
    # A hosted-tool item BoThesis does not model is preserved verbatim so it can
    # be replayed to the provider that produced it.
    return ExtensionItem(**payload)


def _content_part(native: Any) -> ContentPart | None:
    kind = getattr(native, "type", None)
    if kind == "output_text":
        return OutputText(
            text=getattr(native, "text", "") or "",
            annotations=tuple(
                _annotation(annotation)
                for annotation in getattr(native, "annotations", None) or ()
            ),
        )
    if kind == "refusal":
        return Refusal(refusal=getattr(native, "refusal", "") or "")
    if kind == "reasoning_text":
        return ReasoningText(text=getattr(native, "text", "") or "")
    if kind == "summary_text":
        return SummaryText(text=getattr(native, "text", "") or "")
    if kind == "input_text":
        return InputText(text=getattr(native, "text", "") or "")
    return None


def _annotation(native: Any) -> dict[str, Any]:
    return _dump(native) or {}


def _dump(native: Any) -> dict[str, Any] | None:
    dump = getattr(native, "model_dump", None)
    if callable(dump):
        return cast(dict[str, Any], dump(mode="json", exclude_none=True))
    return dict(native) if isinstance(native, dict) else None


__all__ = ["ResponsesStream", "render_input"]
