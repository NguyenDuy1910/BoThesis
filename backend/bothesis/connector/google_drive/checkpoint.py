"""Checkpoint owned by incremental Google Drive source synchronization."""

from bothesis.connector.protocol import ConnectorCheckpoint


class GoogleDriveCheckpoint(ConnectorCheckpoint):
    """Google Drive Changes API cursor tied to one selected source scope."""

    start_page_token: str | None = None
    scope_fingerprint: str | None = None


__all__ = ["GoogleDriveCheckpoint"]
