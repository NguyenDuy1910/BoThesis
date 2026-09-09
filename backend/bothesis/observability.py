"""Provider-neutral observability contracts and the Langfuse adapter."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from bothesis.agent import StepContext, TurnContext
    from bothesis.agent.models import AgentContext, ToolResult
    from bothesis.agent.protocol import Prompt, Response

log = logging.getLogger(__name__)

_MAX_TEXT_CHARACTERS = 512
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|oauth|(?:access|refresh|id)?[_-]?token)$",
    re.IGNORECASE,
)
_CONTENT_KEY = re.compile(r"(?:binary|content|file|image|body|document)", re.IGNORECASE)
_OPAQUE_VALUE_KEY = re.compile(
    r"(?:binary|file_data|image_url|file_url|signed_url|encrypted_content)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TracePayload:
    """A payload whose model-visible text must remain inspectable in a trace."""

    value: object


class TraceSpan(Protocol):
    """The small common surface runtime code needs from an observation."""

    def set_output(self, value: object) -> None: ...

    def set_attribute(self, name: str, value: object) -> None: ...

    def mark_first_token(self) -> None: ...


class Tracer(Protocol):
    """Observability boundary used by the runtime, independent of any SDK."""

    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, object] | None = None,
        input: object | None = None,
    ) -> AbstractContextManager[TraceSpan]: ...

    def generation(
        self,
        name: str,
        *,
        model: str | None,
        attributes: Mapping[str, object] | None = None,
        input: object | None = None,
    ) -> AbstractContextManager[TraceSpan]: ...

    def flush(self) -> None: ...


class TraceSerializer:
    """Build bounded, secret-safe telemetry summaries in one place."""

    @classmethod
    def turn_attributes(cls, ctx: AgentContext, *, turn_id: str) -> dict[str, object]:
        return {
            "conversation_id": ctx.conversation_id,
            "turn_id": turn_id,
            "request_id": ctx.request_id,
            "user_id": _pseudonymous_user_id(ctx.user_id),
        }

    @classmethod
    def turn_input(
        cls,
        *,
        user_input: str,
        model: str | None,
        available_tool_count: int,
        provider: str | None = None,
        resources: Sequence[object] = (),
        available_tools: Sequence[object] = (),
    ) -> dict[str, object]:
        return {
            "user_input": user_input,
            "model": model,
            "provider": provider,
            "resources": [cls.resource_input(resource) for resource in resources],
            "available_tools": cls._tools(available_tools),
            "available_tool_count": available_tool_count,
        }

    @staticmethod
    def turn_output(
        *,
        status: str,
        step_count: int,
        tool_call_count: int,
        final_answer: str = "",
        sources_found: int = 0,
        sources_used: int = 0,
        duration_ms: int = 0,
        model_duration_ms: int = 0,
        tool_duration_ms: int = 0,
    ) -> dict[str, object]:
        return {
            "status": status,
            "step_count": step_count,
            "tool_call_count": tool_call_count,
            "final_answer": final_answer,
            "final_answer_length": len(final_answer),
            "sources_found": sources_found,
            "sources_used": sources_used,
            "duration_ms": duration_ms,
            "model_duration_ms": model_duration_ms,
            "tool_duration_ms": tool_duration_ms,
        }

    @classmethod
    def model_input(
        cls, prompt: Prompt, *, step_context: object, provider_request: object | None = None
    ) -> dict[str, object]:
        """Return the normalized request exactly as the runtime assembled it."""

        context_characters = sum(_item_character_estimate(item) for item in prompt.input)
        payload: dict[str, object] = {
            "step_context": cls.step_context(step_context),
            "normalized_request": {
                "model": prompt.model,
                "instructions": prompt.instructions,
                "input": cls._items(prompt.input),
                "tools": cls._tools(prompt.tools),
                "tool_choice": _model_value(prompt.tool_choice),
                "parallel_tool_calls": prompt.parallel_tool_calls,
                "temperature": prompt.temperature,
                "top_p": prompt.top_p,
                "max_output_tokens": prompt.max_output_tokens,
                "max_tool_calls": prompt.max_tool_calls,
                "store": prompt.store,
                "metadata": prompt.metadata,
                "provider_options": prompt.provider_options,
                # This is runtime lineage, deliberately not forwarded because the
                # full canonical history is replayed on every request.
                "previous_response_id": prompt.previous_response_id,
            },
            "context_metrics": cls._context_metrics(prompt, step_context, context_characters),
        }
        if provider_request is not None:
            payload["provider_request"] = provider_request
        return payload

    @classmethod
    def model_output(cls, response: Response) -> dict[str, object]:
        return {
            "response_id": response.id,
            "status": response.status,
            "finish_reason": _finish_reason(response),
            "model": response.model,
            "usage": _model_value(response.usage),
            "response_items": cls._items(response.output),
            "tool_calls": [
                {"id": call.id, "call_id": call.call_id, "name": call.name, "arguments": call.arguments}
                for call in response.function_calls
            ],
            "output_text": response.output_text,
        }

    @classmethod
    def tool_input(
        cls, *, tool_name: str, arguments: Mapping[str, object]
    ) -> dict[str, object]:
        summary: dict[str, object] = {
            "tool_name": tool_name,
            "arguments": dict(arguments),
        }
        queries = arguments.get("queries")
        if isinstance(queries, list):
            summary["query_count"] = len(queries)
        return summary

    @classmethod
    def tool_output(cls, result: ToolResult) -> dict[str, object]:
        return {
            "status": result.metadata.get("outcome", "completed"),
            "content": result.content,
            "content_preview": cls.text(result.content),
            "result_character_count": len(result.content),
            "error": result.error,
            "metadata": result.metadata,
            "evidence": [_model_value(evidence) for evidence in result.evidence],
            "evidence_count": len(result.evidence),
            "model_content": cls._items(result.model_content),
        }

    @classmethod
    def retrieval_input(cls, *, query: str, result_limit: int) -> dict[str, object]:
        return {"query": query, "result_limit": result_limit}

    @staticmethod
    def retrieval_output(
        *,
        outcome: str,
        result_count: int,
        source_types: Sequence[str],
        duration_ms: int,
        results: Sequence[object] = (),
    ) -> dict[str, object]:
        summary: dict[str, object] = {
            "outcome": outcome,
            "result_count": result_count,
            "source_types": sorted(set(source_types)),
            "duration_ms": duration_ms,
            "results": [_model_value(result) for result in results],
        }
        document_ids = [
            item_id
            for result in results[:5]
            if isinstance((item_id := getattr(result, "item_id", None)), str)
        ]
        if document_ids:
            summary["document_ids"] = document_ids
        scores = [
            score
            for result in results[:5]
            if isinstance((score := getattr(result, "relevance_score", None)), (int, float))
        ]
        if scores:
            summary["top_scores"] = scores
        return summary

    @staticmethod
    def resource_input(resource: object) -> dict[str, object]:
        return {
            "resource_id": getattr(resource, "id", None),
            "name": getattr(resource, "name", None),
            "kind": type(resource).__name__,
            "mime_type": getattr(resource, "mime_type", None),
            "size_bytes": getattr(resource, "size_bytes", None),
        }

    @staticmethod
    def resource_output(
        *, action: str, content_count: int, representation: object | None = None
    ) -> dict[str, object]:
        return {
            "action": action,
            "content_count": content_count,
            "representation": representation,
        }

    @classmethod
    def context_build_input(
        cls,
        turn: TurnContext,
        *,
        previous_observations: Sequence[object] = (),
        available_tools: Sequence[object] = (),
    ) -> dict[str, object]:
        """All inputs considered while assembling a step context."""

        context = turn.environment.agent_context
        return {
            "conversation_state": [
                {"index": index, "role": message.role, "content": message.content}
                for index, message in enumerate(context.history)
            ],
            "current_user_input": cls._user_turn(turn.user_turn),
            "previous_observations": cls._items(previous_observations),
            "available_resources": [cls.resource_input(item) for item in turn.resources],
            "available_tools": cls._tools(available_tools),
            "allowed_tool_names": context.allowed_tool_names,
            "runtime_settings": _model_value(turn.current_settings),
        }

    @classmethod
    def context_build_output(
        cls,
        step_context: StepContext,
        *,
        considered_input: Sequence[object],
        observation_count: int,
    ) -> dict[str, object]:
        return {
            "step_context": cls.step_context(step_context),
            "context_metrics": {
                "considered_input_item_count": len(considered_input),
                "model_input_item_count": len(step_context.input_items),
                "excluded_input_item_count": len(considered_input) - len(step_context.input_items),
                "observation_count": observation_count,
                "context_token_estimate": (
                    sum(_item_character_estimate(item) for item in step_context.input_items) + 3
                ) // 4,
            },
        }

    @classmethod
    def step_context(cls, step_context: object) -> dict[str, object]:
        """Serialize the immutable sampling snapshot without runtime services."""

        return {
            "turn_id": getattr(step_context, "turn_id", None),
            "step_index": getattr(step_context, "step_index", None),
            "settings": _model_value(getattr(step_context, "settings", None)),
            "instructions": getattr(step_context, "instructions", None),
            "input_items": cls._items(getattr(step_context, "input_items", ())),
            "tools": cls._tools(getattr(step_context, "tools", ())),
        }

    @classmethod
    def observation(
        cls, *, call: object, result: ToolResult, included_in_next_step: bool
    ) -> dict[str, object]:
        return {
            "observation_id": f"tool-output:{getattr(call, 'call_id', '')}",
            "source_tool_call": {
                "tool_call_id": getattr(call, "call_id", None),
                "tool_name": getattr(call, "name", None),
            },
            "type": "function_call_output",
            "result": cls.tool_output(result),
            "included_in_next_step": included_in_next_step,
        }

    @staticmethod
    def full(value: object) -> TracePayload:
        """Keep model-visible content intact, after secret/opaque-value filtering."""

        return TracePayload(value)

    @classmethod
    def text(cls, value: str) -> str:
        cleaned = _redact_text(value)
        if len(cleaned) <= _MAX_TEXT_CHARACTERS:
            return cleaned
        return f"{cleaned[: _MAX_TEXT_CHARACTERS - 1]}…"

    @classmethod
    def value(cls, value: object, *, key: str | None = None) -> object:
        """Sanitize SDK-bound values from future callers consistently."""

        if key and _SENSITIVE_KEY.search(key):
            return "[redacted]"
        if key and _CONTENT_KEY.search(key):
            return {"omitted": True, "character_count": _value_length(value)}
        if isinstance(value, str):
            return cls.text(value)
        if isinstance(value, Enum):
            return cls.value(value.value, key=key)
        if isinstance(value, BaseException):
            return {"type": type(value).__name__, "message": cls.text(str(value))}
        if is_dataclass(value) and not isinstance(value, type):
            return cls.value(asdict(value), key=key)
        if hasattr(value, "model_dump"):
            return cls.value(value.model_dump(mode="json", exclude_none=True), key=key)
        if isinstance(value, Mapping):
            return {
                str(item_key): cls.value(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [cls.value(item) for item in value[:20]]
        if isinstance(value, (bytes, bytearray)):
            return {"omitted": True, "byte_count": len(value)}
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return cls.text(str(value))

    @classmethod
    def full_value(cls, value: object, *, key: str | None = None) -> object:
        """Serialize model-visible data without summary truncation.

        Credentials and opaque provider/storage values remain unavailable even
        in detailed traces. Text visible to the model remains whole.
        """

        if key and _SENSITIVE_KEY.search(key):
            return "[redacted]"
        if key and _OPAQUE_VALUE_KEY.search(key):
            return {"omitted": True, "character_count": _value_length(value)}
        if isinstance(value, str):
            return _redact_text(value)
        if isinstance(value, Enum):
            return cls.full_value(value.value, key=key)
        if isinstance(value, BaseException):
            return {"type": type(value).__name__, "message": _redact_text(str(value))}
        if is_dataclass(value) and not isinstance(value, type):
            return cls.full_value(asdict(value), key=key)
        if hasattr(value, "model_dump"):
            return cls.full_value(value.model_dump(mode="json", exclude_none=True), key=key)
        if isinstance(value, Mapping):
            return {
                str(item_key): cls.full_value(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [cls.full_value(item) for item in value]
        if isinstance(value, (bytes, bytearray)):
            return {"omitted": True, "byte_count": len(value)}
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return _redact_text(str(value))

    @classmethod
    def _context_metrics(
        cls, prompt: Prompt, step_context: object, context_characters: int
    ) -> dict[str, int]:
        return {
            "message_count": len(prompt.input),
            "tool_count": len(prompt.tools),
            "context_token_estimate": (context_characters + 3) // 4,
            "step_input_item_count": len(getattr(step_context, "input_items", ())),
        }

    @staticmethod
    def _items(items: Sequence[object]) -> list[object]:
        return [_model_value(item) for item in items]

    @staticmethod
    def _tools(tools: Sequence[object]) -> list[object]:
        return [_model_value(tool) for tool in tools]

    @staticmethod
    def _user_turn(turn: object) -> dict[str, object]:
        return {
            "text": getattr(turn, "text", ""),
            "resources": [
                TraceSerializer.resource_input(resource)
                for resource in getattr(turn, "resources", ())
            ],
        }


class NoopTracer:
    """A no-cost tracing implementation for normal disabled operation."""

    def span(
        self, name: str, *, attributes: Mapping[str, object] | None = None, input: object | None = None
    ) -> AbstractContextManager[TraceSpan]:
        del name, attributes, input
        return _noop_span_context()

    def generation(
        self,
        name: str,
        *,
        model: str | None,
        attributes: Mapping[str, object] | None = None,
        input: object | None = None,
    ) -> AbstractContextManager[TraceSpan]:
        del name, model, attributes, input
        return _noop_span_context()

    def flush(self) -> None:
        return None


class LangfuseTracer:
    """Map the small :class:`Tracer` contract onto the Langfuse SDK."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, object] | None = None,
        input: object | None = None,
    ) -> AbstractContextManager[TraceSpan]:
        return self._observation(
            name,
            as_type=_span_type(name),
            attributes=attributes,
            input=input,
        )

    def generation(
        self,
        name: str,
        *,
        model: str | None,
        attributes: Mapping[str, object] | None = None,
        input: object | None = None,
    ) -> AbstractContextManager[TraceSpan]:
        return self._observation(
            name,
            as_type="generation",
            attributes=attributes,
            input=input,
            model=model,
        )

    @contextmanager
    def _observation(
        self,
        name: str,
        *,
        as_type: str,
        attributes: Mapping[str, object] | None,
        input: object | None,
        model: str | None = None,
    ) -> Iterator[TraceSpan]:
        safe_attributes = TraceSerializer.value(dict(attributes or {}))
        if not isinstance(safe_attributes, dict):
            safe_attributes = {}
        start: dict[str, object] = {
            "as_type": as_type,
            "name": name,
            "input": _trace_value(input),
            "metadata": safe_attributes,
        }
        if model:
            start["model"] = model
        manager = self._start(start, safe_attributes)
        if manager is None:
            yield _NoopSpan()
            return
        try:
            observation = manager.__enter__()
        except Exception as error:  # noqa: BLE001 - instrumentation is optional
            _trace_failure("start", error)
            yield _NoopSpan()
            return
        span = _LangfuseSpan(observation)
        try:
            yield span
        except BaseException as error:
            span._record_error(error)
            raise
        finally:
            try:
                manager.__exit__(None, None, None)
            except Exception as error:  # noqa: BLE001 - instrumentation is optional
                _trace_failure("close", error)

    def _start(
        self, start: dict[str, object], attributes: Mapping[str, object]
    ) -> Any | None:
        try:
            if start["name"] != "agent.turn":
                return self._client.start_as_current_observation(**start)
            from langfuse import propagate_attributes

            trace_context = _trace_context(_text_or_none(attributes.get("request_id")))
            return _combined_context(
                self._client.start_as_current_observation(
                    **start, trace_context=trace_context
                ),
                propagate_attributes(
                    user_id=_text_or_none(attributes.get("user_id")),
                    session_id=_text_or_none(attributes.get("conversation_id")),
                    trace_name=_trace_name(_text_or_none(attributes.get("request_id"))),
                    tags=["chat", "enterprise-knowledge"],
                ),
            )
        except Exception as error:  # noqa: BLE001 - instrumentation is optional
            _trace_failure("start", error)
            return None

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as error:  # noqa: BLE001 - instrumentation is optional
            _trace_failure("flush", error)


def create_tracer(public_key: str | None, secret_key: str | None) -> Tracer:
    """Compose the optional Langfuse adapter once at application startup."""

    if not public_key or not secret_key:
        if public_key or secret_key:
            log.warning("langfuse_tracing_disabled reason=incomplete_credentials")
        return NoopTracer()
    try:
        from langfuse import get_client

        return LangfuseTracer(get_client())
    except Exception as error:  # noqa: BLE001 - startup must not disable chat
        _trace_failure("initialize", error)
        return NoopTracer()


@dataclass(slots=True)
class _LangfuseSpan:
    _observation: Any

    def set_output(self, value: object) -> None:
        _safe_update(self._observation, output=_trace_value(value))

    def set_attribute(self, name: str, value: object) -> None:
        _safe_update(self._observation, metadata={name: TraceSerializer.value(value, key=name)})

    def mark_first_token(self) -> None:
        _safe_update(self._observation, completion_start_time=datetime.now(UTC))

    def _record_error(self, error: BaseException) -> None:
        if isinstance(error, (GeneratorExit, asyncio.CancelledError)):
            _safe_update(self._observation, output={"status": "cancelled"}, level="WARNING")
            return
        _safe_update(
            self._observation,
            output={"status": "error", "exception": TraceSerializer.value(error)},
            level="ERROR",
            status_message=type(error).__name__,
        )


class _NoopSpan:
    def set_output(self, value: object) -> None:
        del value

    def set_attribute(self, name: str, value: object) -> None:
        del name, value

    def mark_first_token(self) -> None:
        return None


@contextmanager
def _noop_span_context() -> Iterator[TraceSpan]:
    yield _NoopSpan()


@contextmanager
def _combined_context(first: Any, second: Any) -> Iterator[Any]:
    with first as observation, second:
        yield observation


def _span_type(name: str) -> str:
    if name == "agent.turn":
        return "agent"
    if name.startswith("tool.execute"):
        return "tool"
    if name == "knowledge.retrieve":
        return "retriever"
    return "span"


def _safe_update(observation: Any, **kwargs: object) -> None:
    try:
        observation.update(**kwargs)
    except Exception as error:  # noqa: BLE001 - instrumentation is optional
        _trace_failure("update", error)


def _trace_failure(stage: str, error: Exception) -> None:
    log.warning("langfuse_trace_%s_failed error_category=%s", stage, type(error).__name__)


def _finish_reason(response: Response) -> str:
    if response.incomplete_details is not None:
        return response.incomplete_details.reason
    if response.function_calls:
        return "tool_calls"
    return "stop" if response.status == "completed" else response.status


def _value_length(value: object) -> int:
    if isinstance(value, (str, bytes, bytearray, Sequence, Mapping)):
        return len(value)
    return 0


def _item_character_estimate(item: object) -> int:
    """Estimate model context without serializing a protocol item for tracing."""

    for field_name in ("text", "output", "arguments"):
        value = getattr(item, field_name, None)
        if isinstance(value, str):
            return len(value)
    return 0


def _model_value(value: object) -> object:
    """Project a protocol/dataclass value without applying telemetry policy yet."""

    if is_dataclass(value) and not isinstance(value, type):
        return _model_value(asdict(value))
    if hasattr(value, "model_dump"):
        return _model_value(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, Mapping):
        return {str(key): _model_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_model_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _selected_history_indexes(
    history: Sequence[object], selected: Sequence[object]
) -> list[int]:
    """Map selected messages to source indexes without confusing duplicates."""

    indexes: list[int] = []
    next_index = 0
    for message in selected:
        for index in range(next_index, len(history)):
            if history[index] == message:
                indexes.append(index)
                next_index = index + 1
                break
    return indexes


def _trace_value(value: object) -> object:
    if isinstance(value, TracePayload):
        return TraceSerializer.full_value(value.value)
    return TraceSerializer.value(value)


def _redact_text(value: str) -> str:
    return re.sub(
        r"(?i)\b(?:bearer\s+)?(?:sk-[a-z0-9_-]{12,}|eyJ[a-z0-9_-]{12,})\b",
        "[redacted]",
        value,
    )


def _pseudonymous_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]


def _trace_context(request_id: str | None) -> dict[str, str] | None:
    if not request_id or len(request_id) != 32:
        return None
    try:
        int(request_id, 16)
    except ValueError:
        return None
    return {"trace_id": request_id.lower()}


def _trace_name(request_id: str | None) -> str:
    trace_context = _trace_context(request_id)
    return f"chat-{trace_context['trace_id'][:8]}" if trace_context else "chat-request"


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "LangfuseTracer",
    "NoopTracer",
    "TraceSerializer",
    "TracePayload",
    "TraceSpan",
    "Tracer",
    "create_tracer",
]
