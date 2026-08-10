"""Load and render small file-backed agent prompts."""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

_PROMPT_DIRECTORY = Path(__file__).resolve().parent
_VARIABLE_PATTERN = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")


class PromptRenderError(ValueError):
    """Raised when a prompt name or runtime value is invalid."""


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Return one cached Markdown prompt from the local prompt directory."""

    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise PromptRenderError(f"invalid prompt name: {name!r}")
    path = _PROMPT_DIRECTORY / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PromptRenderError(f"prompt not found: {name}") from exc


def render_prompt(name: str, /, **values: object) -> str:
    """Render XML-safe runtime values without embedding instructions in Python."""

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
        return escape(str(values[match.group(1)]), entities={'"': "&quot;"})

    return _VARIABLE_PATTERN.sub(replace, template)


def render_chat_base(*, current_datetime: str | None = None) -> str:
    """Render the shared system prompt with volatile context at the end."""

    runtime_datetime = current_datetime or datetime.now().astimezone().isoformat(
        timespec="minutes"
    )
    return render_prompt("chat_base", current_datetime=runtime_datetime)


__all__ = [
    "PromptRenderError",
    "load_prompt",
    "render_chat_base",
    "render_prompt",
]
