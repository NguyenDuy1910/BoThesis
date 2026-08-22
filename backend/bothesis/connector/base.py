from __future__ import annotations

import abc
from collections.abc import Generator
from typing import Any, Generic, TypeVar

from .models import (
    ConnectorCheckpoint,
    ConnectorScope,
    SlimItem,
)
from bothesis.knowledge.protocol import AnyItem, CollectionItem, ItemChange

# ---------------------------------------------------------------------------
# Type aliases used throughout the connector layer
# ---------------------------------------------------------------------------

SecondsSinceUnixEpoch = float
"""Seconds-based UNIX timestamp used for time-range scoping."""

CheckpointT = TypeVar("CheckpointT", bound=ConnectorCheckpoint)

DocumentBatch = list[AnyItem]
"""A single batch yielded by a connector containing canonical Items."""

CheckpointOutput = Generator[DocumentBatch, None, CheckpointT]
"""Generator that yields document batches and returns an updated checkpoint."""

GenerateDocumentsOutput = Generator[DocumentBatch, None, None]
"""Simpler generator (no checkpoint) used by load-style connectors."""

GenerateSlimItemOutput = Generator[list[SlimItem], None, None]
"""Yields batches of permission-sync item references."""


# ---------------------------------------------------------------------------
# Credential handling
# ---------------------------------------------------------------------------

class CredentialsProviderInterface(abc.ABC):
    """Provides credentials to connectors at runtime."""

    @abc.abstractmethod
    def get_credentials(self) -> dict[str, Any]:
        ...

    @abc.abstractmethod
    def get_tenant_id(self) -> str: ...

    @abc.abstractmethod
    def get_provider_key(self) -> str: ...

    def is_dynamic(self) -> bool:
        # Return True when credentials may rotate (e.g. OAuth refresh).
        return False

    def set_credentials(self, creds: dict[str, Any]) -> None:
        pass

    def __enter__(self) -> "CredentialsProviderInterface":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class BaseSourceConnector(abc.ABC):
    """Async, normalized connector interface consumed by ingestion workflows."""

    source: str
    checkpoint_model: type[ConnectorCheckpoint] = ConnectorCheckpoint

    @abc.abstractmethod
    async def test_connection(self) -> bool:
        ...

    @abc.abstractmethod
    async def list_scopes(self) -> list[ConnectorScope]:
        ...

    @abc.abstractmethod
    async def discover_changes(
        self,
        checkpoint: ConnectorCheckpoint,
        scope: ConnectorScope,
    ) -> list[ItemChange]:
        ...

    async def fetch_item(self, item_id: str) -> AnyItem:
        """Fetch one canonical item.
        """
        raise NotImplementedError("connector does not implement fetch_item")

    async def fetch_hierarchy(self, scope: ConnectorScope) -> list[AnyItem]:
        del scope
        return []

    @abc.abstractmethod
    def next_checkpoint(self) -> ConnectorCheckpoint:
        ...


class StaticCredentialsProvider(CredentialsProviderInterface):
    """Non-rotating credential provider for configured connector workers."""

    def __init__(
        self,
        tenant_id: str = "default",
        provider_key: str = "static",
        credentials: dict[str, Any] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._provider_key = provider_key
        self._credentials = dict(credentials or {})

    def get_credentials(self) -> dict[str, Any]:
        # Do not expose the provider's mutable credential state to a connector.
        return dict(self._credentials)

    def get_tenant_id(self) -> str:
        return self._tenant_id

    def get_provider_key(self) -> str:
        return self._provider_key

    def set_credentials(self, creds: dict[str, Any]) -> None:
        self._credentials = dict(creds)


class IndexingHeartbeatInterface(abc.ABC):
    """Callback to signal liveliness during long indexing / slim-doc runs."""

    @abc.abstractmethod
    def heartbeat(self) -> None: ...


class LoadConnector(abc.ABC):
    """One-shot connector that loads all documents from the source."""

    @abc.abstractmethod
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Ingest credential dict; optionally return refreshed credentials.
        ...

    @abc.abstractmethod
    def load_from_state(self) -> GenerateDocumentsOutput:
        # Yield document batches from the source.
        ...


class CheckpointedConnector(abc.ABC, Generic[CheckpointT]):
    """Connector that supports incremental ingestion via checkpoints."""

    @abc.abstractmethod
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CheckpointT,
    ) -> CheckpointOutput[CheckpointT]:
        # Yield document batches starting from the given checkpoint.
        ...

    @abc.abstractmethod
    def build_dummy_checkpoint(self) -> CheckpointT:
        # Return a fresh checkpoint for first-time runs.
        ...

    @abc.abstractmethod
    def validate_checkpoint_json(self, checkpoint_json: str) -> CheckpointT:
        # Deserialise and validate a persisted checkpoint.
        ...


class CredentialsConnector(abc.ABC):
    """Mixin — connector that receives a credentials provider."""

    @abc.abstractmethod
    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None: ...


class SlimConnector(abc.ABC):
    """Connector that can enumerate items without fetching content."""

    @abc.abstractmethod
    def retrieve_all_slim_items(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimItemOutput:
        # Enumerate items without fetching content.
        ...


class SlimConnectorWithPermSync(SlimConnector):
    """SlimConnector that additionally supports permission synchronisation."""

    @abc.abstractmethod
    def retrieve_all_slim_items_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimItemOutput:
        # Enumerate items with permission sync metadata.
        ...


class PermissionSyncConnector(abc.ABC):
    """Mixin for connectors that support external-permission retrieval."""

    @abc.abstractmethod
    def retrieve_external_permissions(self) -> dict[str, Any]:
        # Return sourced ACL data for downstream permission sync.
        ...
