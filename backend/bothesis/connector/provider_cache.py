"""Reusable provider-reference cache for document processing pipelines."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.db.models import Item
from bothesis.connector.protocol import ProviderCacheEntry, ProviderFileCache

DEFAULT_MAX_PROVIDER_CACHE_BYTES = 4 * 1024 * 1024


class PostgresProviderFileCache:
    """Store bounded provider references under ``items.metadata``."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_entry_bytes: int = DEFAULT_MAX_PROVIDER_CACHE_BYTES,
    ) -> None:
        if max_entry_bytes < 1:
            raise ValueError("provider cache limit must be greater than zero")
        self._session_factory = session_factory
        self._max_entry_bytes = max_entry_bytes

    async def get(
        self,
        document_id: UUID,
        *,
        provider: str,
        source_fingerprint: str,
    ) -> ProviderCacheEntry | None:
        normalized_provider = _provider(provider)
        async with self._session_factory() as session:
            metadata = await session.scalar(
                select(Item.metadata_).where(
                    Item.id == document_id,
                    Item.status != "deleted",
                )
            )
        if not isinstance(metadata, Mapping):
            return None
        provider_cache = metadata.get("provider_cache")
        if not isinstance(provider_cache, Mapping):
            return None
        raw_entry = provider_cache.get(normalized_provider)
        if not isinstance(raw_entry, Mapping):
            return None
        if _datetime(raw_entry.get("deleted_at")) is not None:
            return None
        if raw_entry.get("source_fingerprint") != source_fingerprint:
            return None
        reference = raw_entry.get("reference")
        if not isinstance(reference, Mapping):
            return None
        expires_at = _datetime(raw_entry.get("expires_at"))
        entry = ProviderCacheEntry(
            provider=normalized_provider,
            source_fingerprint=source_fingerprint,
            reference={str(key): value for key, value in reference.items()},
            expires_at=expires_at,
        )
        return None if entry.is_expired else entry

    async def put(
        self,
        document_id: UUID,
        entry: ProviderCacheEntry,
    ) -> None:
        provider = _provider(entry.provider)
        serialized = {
            "source_fingerprint": entry.source_fingerprint,
            "reference": dict(entry.reference),
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        encoded = json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > self._max_entry_bytes:
            raise ValueError(
                "provider cache entry exceeds the configured metadata limit"
            )
        async with self._session_factory.begin() as session:
            document = await session.scalar(
                select(Item).where(Item.id == document_id).with_for_update()
            )
            if document is None or document.status == "deleted":
                return
            metadata = dict(document.metadata_)
            provider_cache = dict(metadata.get("provider_cache") or {})
            provider_cache[provider] = serialized
            metadata["provider_cache"] = provider_cache
            document.metadata_ = metadata

    async def invalidate(self, document_id: UUID, *, provider: str) -> None:
        normalized_provider = _provider(provider)
        async with self._session_factory.begin() as session:
            document = await session.scalar(
                select(Item).where(Item.id == document_id).with_for_update()
            )
            if document is None:
                return
            metadata = dict(document.metadata_)
            provider_cache = dict(metadata.get("provider_cache") or {})
            raw_entry = provider_cache.get(normalized_provider)
            if not isinstance(raw_entry, Mapping):
                return
            provider_cache[normalized_provider] = {
                **dict(raw_entry),
                "deleted_at": datetime.now(UTC).isoformat(),
            }
            metadata["provider_cache"] = provider_cache
            document.metadata_ = metadata

    async def clear(self, document_id: UUID) -> None:
        async with self._session_factory.begin() as session:
            document = await session.scalar(
                select(Item).where(Item.id == document_id).with_for_update()
            )
            if document is None:
                return
            metadata = dict(document.metadata_)
            provider_cache = metadata.get("provider_cache")
            if not isinstance(provider_cache, Mapping):
                return
            deleted_at = datetime.now(UTC).isoformat()
            metadata["provider_cache"] = {
                str(provider): (
                    {**dict(entry), "deleted_at": deleted_at}
                    if isinstance(entry, Mapping)
                    else entry
                )
                for provider, entry in provider_cache.items()
            }
            document.metadata_ = metadata


def _provider(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or len(normalized) > 64:
        raise ValueError("provider name is invalid")
    return normalized


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "PostgresProviderFileCache",
    "ProviderCacheEntry",
    "ProviderFileCache",
]
