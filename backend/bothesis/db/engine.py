"""Async PostgreSQL engine and unit-of-work helpers."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

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


SessionFactory = Callable[[], AsyncSession]


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


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session suitable for a FastAPI dependency."""

    async with get_session_factory()() as session:
        yield session


async def get_transactional_session() -> AsyncIterator[AsyncSession]:
    """Yield one request unit of work with commit/rollback semantics."""

    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """Commit a unit of work, rolling it back when the operation fails."""

    factory = session_factory or get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


@asynccontextmanager
async def get_connection(
    engine: AsyncEngine | None = None,
) -> AsyncIterator[AsyncConnection]:
    """Yield a low-level async connection for health checks and migrations."""

    async with (engine or get_engine()).connect() as connection:
        yield connection


__all__ = [
    "LazySessionFactory",
    "SessionFactory",
    "get_connection",
    "get_engine",
    "get_session",
    "get_session_factory",
    "get_transactional_session",
    "session_scope",
]
