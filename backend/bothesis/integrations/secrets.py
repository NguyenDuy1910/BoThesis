"""Development secret references backed by JSON environment variables."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any


class EnvironmentSecretResolver:
    """Resolve only explicit ``env://NAME`` references at runtime."""

    async def resolve(self, reference: str) -> Mapping[str, Any]:
        prefix = "env://"
        if not reference.startswith(prefix):
            raise ValueError("only env:// credential references are configured")
        variable_name = reference.removeprefix(prefix).strip()
        if not variable_name or not variable_name.replace("_", "").isalnum():
            raise ValueError("credential environment variable name is invalid")
        raw_value = os.getenv(variable_name)
        if raw_value is None:
            raise LookupError("credential reference is not configured")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ValueError("credential environment value must be a JSON object") from exc
        if not isinstance(value, dict):
            raise ValueError("credential environment value must be a JSON object")
        return value


__all__ = ["EnvironmentSecretResolver"]
