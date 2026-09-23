"""Async PostgreSQL engine and unit-of-work helpers."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL_ENV = "DATABASE_URL"


def _database_url(value: str | None = None) -> URL:
    raw_url = value or os.getenv(DATABASE_URL_ENV)
    if not raw_url:
        raise RuntimeError(f"{DATABASE_URL_ENV} is required")

    try:
        url = make_url(raw_url)
    except ArgumentError as exc:
        raise ValueError("DATABASE_URL is not a valid SQLAlchemy URL") from exc

    if url.drivername in {"postgres", "postgresql"}:
        return url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        raise ValueError("DATABASE_URL must use PostgreSQL with the asyncpg driver")
    return url


@lru_cache(maxsize=8)
def _create_engine(url: URL, echo: bool) -> AsyncEngine:
    return create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
    )


def get_engine(
    database_url: str | None = None,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Return a cached async PostgreSQL engine without opening a connection."""

    return _create_engine(_database_url(database_url), echo)


def get_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Build a session factory bound to the configured database engine."""

    return async_sessionmaker(
        bind=engine or get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


class SessionFactory(Protocol):
    """Factory surface required by application database operation scopes."""

    def __call__(self, **local_kw: Any) -> AsyncSession: ...

    def begin(self) -> Any: ...


class LazySessionFactory:
    """Stand in for a session factory, opening the engine on first use.

    Building the engine reads ``DATABASE_URL``, so deferring it keeps request
    validation and application wiring independent of database configuration.
    Every other attribute — ``begin``, ``kw``, and the rest of the
    ``async_sessionmaker`` surface callers rely on — is forwarded unchanged.
    """

    __slots__ = ("_factory",)

    def __init__(self) -> None:
        self._factory: async_sessionmaker[AsyncSession] | None = None

    def resolve(self) -> async_sessionmaker[AsyncSession]:
        """Return the real factory, creating the engine the first time."""

        factory = self._factory
        if factory is None:
            factory = get_session_factory()
            self._factory = factory
        return factory

    def __call__(self, **local_kw: Any) -> AsyncSession:
        return self.resolve()(**local_kw)

    def __getattr__(self, name: str) -> Any:
        # ``_factory`` lives in ``__slots__``; reaching here for it would mean
        # the instance was never initialized, and resolving would recurse.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.resolve(), name)


@asynccontextmanager
async def transaction_scope(
    session_factory: SessionFactory | None = None,
) -> AsyncIterator[AsyncSession]:
    """Run exactly one database operation scope.

    ``async_sessionmaker.begin()`` owns session creation, transaction start,
    commit/rollback, and connection release. Callers must finish all database
    work inside this scope and perform external or long-running work after it.
    """

    factory = session_factory or get_session_factory()
    async with factory.begin() as session:
        yield session


@asynccontextmanager
async def get_connection(
    engine: AsyncEngine | None = None,
) -> AsyncIterator[AsyncConnection]:
    """Yield one explicit low-level transaction for health checks/migrations."""

    async with (engine or get_engine()).begin() as connection:
        yield connection


@asynccontextmanager
async def advisory_lock_scope(
    lock_key: int,
    *,
    engine: AsyncEngine | None = None,
) -> AsyncIterator[None]:
    """Hold one PostgreSQL advisory lock without holding a transaction.

    Session-level advisory locks must stay on one connection, but indexing and
    other long-running work must not keep an implicit transaction open. An
    autocommit connection gives the lock session ownership and releases it on
    connection close.
    """

    async with (engine or get_engine()).connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(
            text("SELECT pg_advisory_lock(:lock_key)"), {"lock_key": lock_key}
        )
        try:
            yield
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key}
            )


__all__ = [
    "LazySessionFactory",
    "SessionFactory",
    "get_connection",
    "get_engine",
    "get_session_factory",
    "advisory_lock_scope",
    "transaction_scope",
]
