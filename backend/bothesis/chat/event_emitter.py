"""Normalize provider stream events used by chat orchestration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bothesis.agent.models import (
    ModelTurn,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    TurnDone,
)


@dataclass(frozen=True, slots=True)
class StreamCompleted:
    turn: ModelTurn
    duration_ms: int


class ModelTurnAccumulator:
    """Collect one provider stream into a normalized model turn."""

    def __init__(self) -> None:
        self._text: list[str] = []
        self._finish_reason: str | None = None
        self._model: str | None = None
        self._usage: dict[str, int] = {}
        self._tool_call_deltas: dict[str, dict[str, str]] = {}
        self._tool_calls: list[ToolCall] = []

    def feed(self, event: TextDelta | ToolCallDelta | TurnDone) -> None:
        if isinstance(event, TextDelta):
            self._text.append(event.delta)
            return
        if isinstance(event, ToolCallDelta):
            pending = self._tool_call_deltas.setdefault(
                event.call_id,
                {"name": "", "arguments": ""},
            )
            pending["name"] += event.name
            pending["arguments"] += event.arguments
            return
        self._finish_reason = event.finish_reason
        self._model = event.model
        self._usage = event.usage
        self._tool_calls = _normalize_tool_calls(event.tool_calls)

    def result(self) -> ModelTurn:
        tool_calls = self._tool_calls or _tool_calls_from_deltas(self._tool_call_deltas)
        return ModelTurn(
            text="".join(self._text),
            tool_calls=tool_calls,
            finish_reason=self._finish_reason,
            model=self._model,
            usage=self._usage,
        )


def _normalize_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    used_call_ids: set[str] = set()
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, Mapping):
            continue
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        call_id = raw_call.get("id")
        normalized_call_id = (
            call_id.strip()
            if isinstance(call_id, str) and call_id.strip()
            else f"call_{index}"
        )
        if normalized_call_id in used_call_ids:
            normalized_call_id = f"{normalized_call_id}_{index}"
        used_call_ids.add(normalized_call_id)
        calls.append(
            ToolCall(
                call_id=normalized_call_id,
                name=name.strip(),
                arguments=_tool_arguments(function.get("arguments")),
            )
        )
    return calls


def _tool_calls_from_deltas(
    deltas: Mapping[str, Mapping[str, str]],
) -> list[ToolCall]:
    return [
        ToolCall(
            call_id=call_id,
            name=value["name"].strip(),
            arguments=_tool_arguments(value["arguments"]),
        )
        for call_id, value in deltas.items()
        if value["name"].strip()
    ]


def _tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, Mapping):
        return dict(raw_arguments)
    if not isinstance(raw_arguments, str) or not raw_arguments.strip():
        return {}
    try:
        value = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = ["ModelTurnAccumulator", "StreamCompleted"]
