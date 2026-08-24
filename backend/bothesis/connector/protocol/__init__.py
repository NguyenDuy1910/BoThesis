"""Canonical source, content, chunk, access, and connector contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from .access import AccessEffect, AccessPolicy, AccessRule, DirectAccess, EffectiveAccess, Principal
from .changes import ChangeType, ItemChange
from .checkpoint import ConnectorCheckpoint, SourceCheckpoint
from .chunks import Chunk
from .citation import BoundingBox, CitationInfo, CitationSpan
from .content import AnyContentPart, CodePart, ImagePart, LinkPart, StructuredPart, TablePart, TextPart
from .hierarchy import Hierarchy
from .items import AnyItem, CollectionItem, CollectionKind, ConnectorFailure, DocumentItem, DocumentKind, Item, ItemFailure, SlimItem
from .scope import ConnectorScope
from .source import SourceIdentity, SourceProvider
from .storage import RawObjectStore, StorageObject


@dataclass(frozen=True, slots=True)
class ProviderCacheEntry:
    """Bounded provider reference associated with canonical source content."""

    provider: str
    provider_version: str
    reference: Mapping[str, Any]
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.now(UTC)


@runtime_checkable
class ProviderFileCache(Protocol):
    """Provider-reference cache boundary used outside connector adapters."""

    async def get(
        self,
        document_id: UUID,
        *,
        provider: str,
        provider_version: str,
    ) -> ProviderCacheEntry | None: ...

    async def put(
        self,
        document_id: UUID,
        entry: ProviderCacheEntry,
    ) -> None: ...

    async def invalidate(self, document_id: UUID, *, provider: str) -> None: ...

    async def clear(self, document_id: UUID) -> None: ...

__all__ = [
    "AccessEffect", "AccessPolicy", "AccessRule", "AnyContentPart", "AnyItem",
    "BoundingBox", "ChangeType", "Chunk", "CitationInfo", "CitationSpan",
    "CodePart", "CollectionItem", "CollectionKind", "ConnectorCheckpoint",
    "ConnectorFailure",
    "ConnectorScope", "DirectAccess", "DocumentItem", "DocumentKind",
    "EffectiveAccess", "Hierarchy", "ImagePart", "Item", "ItemChange",
    "ItemFailure", "LinkPart", "Principal", "ProviderCacheEntry",
    "ProviderFileCache", "SourceCheckpoint",
    "SlimItem", "SourceIdentity", "SourceProvider", "StructuredPart", "TablePart", "TextPart",
    "RawObjectStore", "StorageObject",
]
