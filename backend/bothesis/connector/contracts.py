"""Small infrastructure contracts shared by connector adapters.

Connector code depends on these protocols instead of a concrete storage
implementation. This keeps source adapters usable in workers, tests, and API
processes without importing the rest of the ingestion stack.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageContract(Protocol):
    """Raw-file storage behavior needed by attachment connectors."""

    def save_bytes(self, data: bytes, key: str) -> None:
        """Persist ``data`` under ``key`` or raise on failure."""


__all__ = ["StorageContract"]
