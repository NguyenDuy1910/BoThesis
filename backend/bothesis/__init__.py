"""Shared provider-neutral contracts for the BoThesis application."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from xml.sax.saxutils import escape

_PROMPT_DIRECTORY = Path(__file__).resolve().parent / "agent" / "prompts"
_VARIABLE_PATTERN = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")


class PromptRenderError(ValueError):
    """Raised when a prompt name or runtime value is invalid."""


@runtime_checkable
class ModelResponseClient(Protocol):
    """Non-streaming OpenResponses boundary used outside the agent runtime."""

    model: str | None

    async def responses(
        self,
        *,
        input: Any,
        model: str | None = None,
        **params: Any,
    ) -> Any:
        """Return one completed provider response."""
        ...


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Return one cached Markdown prompt from the shared prompt directory."""

    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise PromptRenderError(f"invalid prompt name: {name!r}")
    path = _PROMPT_DIRECTORY / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PromptRenderError(f"prompt not found: {name}") from exc


def render_prompt(name: str, /, **values: object) -> str:
    """Render typed runtime values without double-encoding structured JSON."""

    template = load_prompt(name)
    expected = set(_VARIABLE_PATTERN.findall(template))
    supplied = set(values)
    if missing := expected - supplied:
        names = ", ".join(sorted(missing))
        raise PromptRenderError(f"missing prompt values: {names}")
    if unexpected := supplied - expected:
        names = ", ".join(sorted(unexpected))
        raise PromptRenderError(f"unexpected prompt values: {names}")

    def replace(match: re.Match[str]) -> str:
        variable = match.group(1)
        return _render_prompt_value(variable, values[variable])

    return _VARIABLE_PATTERN.sub(replace, template)


def _render_prompt_value(variable: str, value: object) -> str:
    if isinstance(value, str):
        return escape(value)
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PromptRenderError(
            f"prompt value is not JSON serializable: {variable}"
        ) from exc
    return (
        serialized.replace("&", r"\u0026")
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
    )


def render_agent_base() -> str:
    """Return the primary conversational-agent instruction."""

    return render_prompt("agent_base")


__all__ = [
    "ModelResponseClient",
    "PromptRenderError",
    "load_prompt",
    "render_agent_base",
    "render_prompt",
]
