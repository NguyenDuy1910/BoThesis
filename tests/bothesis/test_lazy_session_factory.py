"""The lazy session factory must stand in for a real ``async_sessionmaker``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from bothesis.db import engine as engine_module
from bothesis.db.engine import LazySessionFactory

# Every attribute the application reaches for on its session factory. A proxy
# that forwards only ``__call__`` breaks ``session_factory.begin()`` at runtime
# while every stubbed test still passes.
FORWARDED_ATTRIBUTES = ("begin", "kw")


def test_engine_is_not_built_until_a_session_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    calls: list[int] = []

    def fail() -> None:
        calls.append(1)
        raise RuntimeError("DATABASE_URL is required")

    monkeypatch.setattr(engine_module, "get_session_factory", fail)
    factory = LazySessionFactory()

    assert calls == []

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        factory()

    assert calls == [1]


@pytest.mark.parametrize("attribute", FORWARDED_ATTRIBUTES)
def test_session_maker_attributes_are_forwarded(
    monkeypatch: pytest.MonkeyPatch, attribute: str
) -> None:
    sentinel = object()
    real = type("Sessionmaker", (), {attribute: sentinel})()
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: real)

    assert getattr(LazySessionFactory(), attribute) is sentinel


def test_calling_the_factory_opens_a_session_from_the_real_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    monkeypatch.setattr(
        engine_module, "get_session_factory", lambda: lambda **_: session
    )
    factory = LazySessionFactory()

    assert factory() is session
    assert factory() is session


def test_the_real_factory_is_built_once(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[int] = []

    def build() -> object:
        built.append(1)
        return lambda **_: object()

    monkeypatch.setattr(engine_module, "get_session_factory", build)
    factory = LazySessionFactory()
    factory()
    factory()

    assert built == [1]


def test_private_attributes_do_not_resolve_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing dunder must not recurse into building the engine."""

    monkeypatch.setattr(
        engine_module,
        "get_session_factory",
        lambda: pytest.fail("engine built for a private attribute"),
    )

    with pytest.raises(AttributeError):
        LazySessionFactory()._not_a_real_attribute


def test_runtime_hands_services_a_usable_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime's factory must satisfy the surface services call on it."""

    real = type("Sessionmaker", (), {attr: object() for attr in FORWARDED_ATTRIBUTES})()
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: real)

    from bothesis.runtime import AppRuntime

    sessions = AppRuntime().sessions()

    for attribute in FORWARDED_ATTRIBUTES:
        assert getattr(sessions, attribute) is getattr(real, attribute)
