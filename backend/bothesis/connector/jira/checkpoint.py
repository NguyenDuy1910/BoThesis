from __future__ import annotations

from ..models import ConnectorCheckpoint


class JiraCheckpoint(ConnectorCheckpoint):
    last_updated_at: str | None = None
    start_at: int = 0
