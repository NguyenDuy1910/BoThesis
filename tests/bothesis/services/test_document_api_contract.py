from __future__ import annotations

import json
from pathlib import Path

import pytest

from main import (
    _environment_boolean,
    _phase1_unscoped_retrieval_enabled,
)


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


def test_phase1_unscoped_retrieval_requires_insecure_development_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOTHESIS_PHASE1_UNSCOPED_RETRIEVAL", "true")
    monkeypatch.setenv("BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY", "false")

    with pytest.raises(RuntimeError, match="requires"):
        _phase1_unscoped_retrieval_enabled()

    monkeypatch.setenv("BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY", "true")
    assert _phase1_unscoped_retrieval_enabled() is True
