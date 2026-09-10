"""Translate OpenRouter shell items at the provider boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from bothesis.agent.protocol import (
    ExecutionEnvironmentRef,
    ExecutionOutput,
    HostedExecutionCallItem,
    HostedExecutionResultItem,
    Item,
    ProviderResourceRef,
)


class OpenRouterExecutionMapper:
    """Normalize hosted shell observations and render them back for replay."""

    _CALL_TYPES = frozenset({"shell_call", "openrouter:shell"})
    _RESULT_TYPES = frozenset({"shell_call_output", "openrouter_shell_tool_result"})

    def normalize_output_item(self, native: Any) -> Item | None:
        """Return a provider-neutral shell item or leave unrelated output alone."""

        payload = _payload(native)
        kind = payload.get("type")
        # OpenRouter completes a hosted shell as one ``openrouter:shell`` item
        # that carries both the requested action and its command output.
        if kind == "openrouter:shell" and isinstance(
            payload.get("output", payload.get("content")), list
        ):
            return self._result(payload)
        if kind in self._CALL_TYPES and isinstance(payload.get("action"), dict):
            return self._call(payload)
        if kind in self._RESULT_TYPES:
            return self._result(payload)
        return None

    def render_input(
        self, input_items: str | Sequence[object]
    ) -> str | list[object]:
        """Convert generic hosted observations into OpenRouter's native replay form."""

        if isinstance(input_items, str):
            return input_items
        return [self._render_item(item) for item in input_items]

    def _call(self, payload: dict[str, Any]) -> HostedExecutionCallItem:
        action = payload["action"]
        commands = action.get("commands")
        if not isinstance(commands, list) or not all(
            isinstance(command, str) and command for command in commands
        ):
            raise ValueError("OpenRouter shell call does not contain commands")
        return HostedExecutionCallItem(
            id=_text(payload.get("id")),
            call_id=_call_id(payload, "shell call id"),
            commands=tuple(commands),
            status=_status(payload.get("status")),
            timeout_ms=_positive_int(action.get("timeout_ms")),
            max_output_characters=_positive_int(action.get("max_output_length")),
            environment=_environment(payload),
        )

    def _result(self, payload: dict[str, Any]) -> HostedExecutionResultItem:
        raw_output = payload.get("output", payload.get("content", ()))
        if not isinstance(raw_output, list):
            raise ValueError("OpenRouter shell result does not contain command output")
        return HostedExecutionResultItem(
            id=_text(payload.get("id")),
            call_id=_call_id(payload, "shell result call id"),
            output=tuple(_output(entry) for entry in raw_output),
            commands=_commands(payload),
            status=_status(payload.get("status")),
            environment=_environment(payload),
            files=_files(payload),
            workspace_files=_workspace_file_names(payload),
        )

    def _render_item(self, item: object) -> object:
        if not isinstance(item, dict):
            return item
        kind = item.get("type")
        if kind == "hosted_execution_call":
            return _native_call(item)
        if kind == "hosted_execution_result":
            return _native_result(item)
        return item


def _payload(native: Any) -> dict[str, Any]:
    dump = getattr(native, "model_dump", None)
    if callable(dump):
        value = dump(mode="json", exclude_none=True)
        if isinstance(value, dict):
            return value
    return dict(native) if isinstance(native, dict) else {}


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"OpenRouter {label} is missing")
    return value


def _call_id(payload: dict[str, Any], label: str) -> str:
    return _required_text(
        payload.get("call_id") or payload.get("tool_call_id") or payload.get("id"),
        label,
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _status(value: object) -> str | None:
    return value if value in {"in_progress", "completed", "incomplete"} else None


def _environment(payload: dict[str, Any]) -> ExecutionEnvironmentRef | None:
    raw_environment = payload.get("environment")
    environment = raw_environment if isinstance(raw_environment, dict) else {}
    identifier = _text(payload.get("container_id")) or _text(
        environment.get("container_id")
    )
    return (
        ExecutionEnvironmentRef(provider="openrouter", id=identifier)
        if identifier is not None
        else None
    )


def _output(value: object) -> ExecutionOutput:
    if not isinstance(value, dict):
        raise ValueError("OpenRouter shell command output is invalid")
    outcome = value.get("outcome")
    if not isinstance(outcome, dict):
        raise ValueError("OpenRouter shell command outcome is invalid")
    if outcome.get("type") == "timeout":
        return ExecutionOutput(
            stdout=str(value.get("stdout") or ""),
            stderr=str(value.get("stderr") or ""),
            timed_out=True,
        )
    exit_code = outcome.get("exit_code")
    if outcome.get("type") != "exit" or (
        isinstance(exit_code, bool) or not isinstance(exit_code, int)
    ):
        raise ValueError("OpenRouter shell command outcome is invalid")
    return ExecutionOutput(
        stdout=str(value.get("stdout") or ""),
        stderr=str(value.get("stderr") or ""),
        exit_code=exit_code,
    )


def _commands(payload: dict[str, Any]) -> tuple[str, ...]:
    """Keep commands when OpenRouter combines an action with its result."""

    action = payload.get("action")
    raw_commands = action.get("commands") if isinstance(action, dict) else None
    if not isinstance(raw_commands, list) or not all(
        isinstance(command, str) and command for command in raw_commands
    ):
        return ()
    return tuple(raw_commands)


def _files(payload: dict[str, Any]) -> tuple[ProviderResourceRef, ...]:
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        return ()
    files: list[ProviderResourceRef] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            continue
        identifier = _text(entry.get("file_id")) or _text(entry.get("id"))
        if identifier is None:
            continue
        name = _text(entry.get("filename")) or _text(entry.get("path"))
        files.append(ProviderResourceRef(provider="openrouter", id=identifier, name=name))
    return tuple(files)


def _workspace_file_names(payload: dict[str, Any]) -> tuple[str, ...]:
    """Keep only safe reported names for public execution progress."""

    result: list[str] = []
    for file in _files(payload):
        if file.name is not None and file.name not in result:
            result.append(file.name)
    return tuple(result)


def _native_call(item: dict[str, Any]) -> dict[str, Any]:
    action: dict[str, Any] = {"commands": list(item["commands"])}
    if item.get("timeout_ms") is not None:
        action["timeout_ms"] = item["timeout_ms"]
    if item.get("max_output_characters") is not None:
        action["max_output_length"] = item["max_output_characters"]
    native: dict[str, Any] = {
        "type": "shell_call",
        "call_id": item["call_id"],
        "action": action,
        "status": item.get("status") or "completed",
    }
    if item.get("id") is not None:
        native["id"] = item["id"]
    environment = item.get("environment")
    if isinstance(environment, dict) and environment.get("provider") == "openrouter":
        native["environment"] = {
            "type": "container_reference",
            "container_id": environment["id"],
        }
    return native


def _native_result(item: dict[str, Any]) -> dict[str, Any]:
    output = []
    for entry in item["output"]:
        outcome = (
            {"type": "timeout"}
            if entry.get("timed_out")
            else {"type": "exit", "exit_code": entry["exit_code"]}
        )
        output.append(
            {
                "stdout": entry.get("stdout", ""),
                "stderr": entry.get("stderr", ""),
                "outcome": outcome,
            }
        )
    native: dict[str, Any] = {
        "type": "shell_call_output",
        "call_id": item["call_id"],
        "output": output,
        "status": item.get("status") or "completed",
    }
    if item.get("id") is not None:
        native["id"] = item["id"]
    environment = item.get("environment")
    if isinstance(environment, dict) and environment.get("provider") == "openrouter":
        native["container_id"] = environment["id"]
    files = item.get("files")
    if isinstance(files, list):
        native_files = []
        for file in files:
            if not isinstance(file, dict) or file.get("provider") != "openrouter":
                continue
            native_file = {"type": "container_file_citation", "file_id": file["id"]}
            if file.get("name") is not None:
                native_file["filename"] = file["name"]
            if "container_id" in native:
                native_file["container_id"] = native["container_id"]
            native_files.append(native_file)
        if native_files:
            native["files"] = native_files
    return native


__all__ = ["OpenRouterExecutionMapper"]
