"""Adapters between legacy batch crawlers and the normalized async contract."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .base import BaseSourceConnector, CheckpointedConnector
from .models import (
    ConnectorCheckpoint,
    ConnectorScope,
    Document,
    HierarchyNode,
    SourceACL,
    SourceChange,
    SourceDocument,
)


class CheckpointedSourceConnectorAdapter(BaseSourceConnector):
    """Run a synchronous checkpoint crawler off-loop and expose async lookups.

    The temporary document/hierarchy maps are swapped only after a complete
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
        self._documents: dict[str, SourceDocument] = {}
        self._hierarchy: dict[str, HierarchyNode] = {}
        self._next_checkpoint: ConnectorCheckpoint = connector.build_dummy_checkpoint()

    async def test_connection(self) -> bool:
        validator = getattr(self.connector, "validate_connector_settings", None)
        if validator is None:
            return True
        await asyncio.to_thread(validator)
        return True

    async def list_scopes(self) -> list[ConnectorScope]:
        return [scope.model_copy(deep=True) for scope in self.scopes]

    async def discover_changes(
        self,
        checkpoint: ConnectorCheckpoint,
        scope: ConnectorScope,
    ) -> list[SourceChange]:
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
            list[SourceChange],
            dict[str, SourceDocument],
            dict[str, HierarchyNode],
            ConnectorCheckpoint,
        ]:
            changes: list[SourceChange] = []
            documents: dict[str, SourceDocument] = {}
            hierarchy: dict[str, HierarchyNode] = {}
            generator = self.connector.load_from_checkpoint(0.0, end, typed_checkpoint)
            while True:
                try:
                    batch = next(generator)
                except StopIteration as stop:
                    next_checkpoint = stop.value or typed_checkpoint
                    return changes, documents, hierarchy, next_checkpoint
                for item in batch:
                    if isinstance(item, Document):
                        document = SourceDocument.from_document(item)
                        documents[document.external_id] = document
                        changes.append(
                            SourceChange(
                                external_id=document.external_id,
                                external_version=document.external_version,
                                etag=document.etag,
                                last_modified_at=document.doc_updated_at,
                            )
                        )
                    elif isinstance(item, HierarchyNode):
                        hierarchy[item.raw_node_id] = item

        changes, documents, hierarchy, next_checkpoint = await asyncio.to_thread(crawl)
        self._documents = documents
        self._hierarchy = hierarchy
        self._next_checkpoint = next_checkpoint
        return changes

    async def fetch_document(self, external_id: str) -> SourceDocument:
        try:
            return self._documents[external_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"Document {external_id!r} was not discovered") from exc

    async def fetch_acl(self, external_id: str) -> SourceACL:
        return (await self.fetch_document(external_id)).acl

    async def fetch_hierarchy(self, scope: ConnectorScope) -> list[HierarchyNode]:
        del scope
        return [node.model_copy(deep=True) for node in self._hierarchy.values()]

    def next_checkpoint(self) -> ConnectorCheckpoint:
        return self._next_checkpoint.model_copy(deep=True)


__all__ = ["CheckpointedSourceConnectorAdapter"]
