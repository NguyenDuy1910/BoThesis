"""Adapters between checkpoint crawlers and the canonical async contract."""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

from .base import BaseSourceConnector, CheckpointedConnector
from bothesis.connector.protocol import (
    AnyItem,
    Chunk,
    CollectionItem,
    ConnectorCheckpoint,
    ConnectorScope,
    ChangeType,
    DocumentItem,
    ItemChange,
    RawObjectStore,
)


class CheckpointedSourceConnectorAdapter(BaseSourceConnector):
    """Run a synchronous checkpoint crawler off-loop and expose async lookups.

    The temporary item/hierarchy maps are swapped only after a complete
    crawl, so a failed source request cannot expose partial state or advance a
    checkpoint.
    """

    def __init__(
        self,
        *,
        source: str,
        connector: CheckpointedConnector,
        scopes: list[ConnectorScope],
    ) -> None:
        if not source.strip():
            raise ValueError("source is required")
        if not scopes:
            raise ValueError("at least one connector scope is required")
        self.source = source.strip()
        self.connector = connector
        self.scopes = list(scopes)
        self.checkpoint_model = type(connector.build_dummy_checkpoint())
        self._items: dict[str, AnyItem] = {}
        self._hierarchy: dict[str, AnyItem] = {}
        self._next_checkpoint: ConnectorCheckpoint = connector.build_dummy_checkpoint()

    async def test_connection(self) -> bool:
        validator = getattr(self.connector, "validate_connector_settings", None)
        if validator is None:
            return True
        await asyncio.to_thread(validator)
        return True

    async def list_scopes(self) -> list[ConnectorScope]:
        return [scope.model_copy(deep=True) for scope in self.scopes]

    def set_storage(self, storage: RawObjectStore) -> None:
        """Forward object storage to crawlers that persist original content."""

        setter = getattr(self.connector, "set_storage", None)
        if setter is not None:
            setter(storage)

    async def discover_changes(
        self,
        checkpoint: ConnectorCheckpoint,
        scope: ConnectorScope,
    ) -> list[ItemChange]:
        if not any(
            candidate.scope_type == scope.scope_type
            and candidate.scope_value == scope.scope_value
            for candidate in self.scopes
        ):
            raise ValueError(f"Unknown connector scope: {scope.scope_type}:{scope.scope_value}")
        typed_checkpoint = (
            checkpoint
            if isinstance(checkpoint, self.checkpoint_model)
            else self.checkpoint_model.model_validate(checkpoint.model_dump())
        )
        end = datetime.now(timezone.utc).timestamp()

        def crawl() -> tuple[
            list[ItemChange],
            dict[str, AnyItem],
            dict[str, AnyItem],
            ConnectorCheckpoint,
        ]:
            changes: list[ItemChange] = []
            items: dict[str, AnyItem] = {}
            hierarchy: dict[str, AnyItem] = {}
            generator = self.connector.load_from_checkpoint(0.0, end, typed_checkpoint)
            while True:
                try:
                    batch = next(generator)
                except StopIteration as stop:
                    next_checkpoint = stop.value or typed_checkpoint
                    return changes, items, hierarchy, next_checkpoint
                for item in batch:
                    if isinstance(item, DocumentItem):
                        normalized = item
                        items[normalized.id] = normalized
                        changes.append(
                            ItemChange(
                                type=ChangeType.UPDATED,
                                item_id=normalized.id,
                                item=normalized,
                                provider_version=normalized.source.external_version,
                                occurred_at=normalized.updated_at,
                            )
                        )
                    elif isinstance(item, CollectionItem):
                        hierarchy[item.id] = item

        changes, items, hierarchy, next_checkpoint = await asyncio.to_thread(crawl)
        self._items = items
        self._hierarchy = hierarchy
        self._next_checkpoint = next_checkpoint
        return changes

    async def fetch_item(self, external_id: str) -> AnyItem:
        try:
            return self._items[external_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"Item {external_id!r} was not discovered") from exc

    async def fetch_chunks(self, item: DocumentItem) -> tuple[Chunk, ...] | None:
        """Forward source-owned chunks when the checkpoint connector provides them."""

        fetcher = getattr(self.connector, "fetch_chunks", None)
        if fetcher is None:
            return None
        chunks = fetcher(item)
        if inspect.isawaitable(chunks):
            chunks = await chunks
        return tuple(chunks) if chunks is not None else None

    async def fetch_hierarchy(self, scope: ConnectorScope) -> list[AnyItem]:
        del scope
        return [item.model_copy(deep=True) for item in self._hierarchy.values()]

    def next_checkpoint(self) -> ConnectorCheckpoint:
        return self._next_checkpoint.model_copy(deep=True)


__all__ = ["CheckpointedSourceConnectorAdapter"]
