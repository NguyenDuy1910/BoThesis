from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.env_config import boolean as _environment_boolean


def test_backend_source_contains_no_physical_delete_operations() -> None:
    backend_root = Path(__file__).resolve().parents[3] / "backend" / "bothesis"
    forbidden_operations = (
        "from sqlalchemy import delete",
        "session.delete(",
        "delete_object(",
        ".client.delete(",
    )
    offenders = {
        str(path.relative_to(backend_root)): operation
        for path in backend_root.rglob("*.py")
        for operation in forbidden_operations
        if operation in path.read_text(encoding="utf-8")
    }

    assert offenders == {}


def test_environment_boolean_requires_a_json_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setting_name = "BOTHESIS_TEST_BOOLEAN"
    monkeypatch.delenv(setting_name, raising=False)
    assert _environment_boolean(setting_name) is False

    monkeypatch.setenv(setting_name, json.dumps(True))
    assert _environment_boolean(setting_name) is True

    monkeypatch.setenv(setting_name, json.dumps({"enabled": True}))
    with pytest.raises(RuntimeError, match="must be a JSON boolean"):
        _environment_boolean(setting_name)
