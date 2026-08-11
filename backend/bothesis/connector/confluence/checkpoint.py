from __future__ import annotations

from ..models import ConnectorCheckpoint


class ConfluenceCheckpoint(ConnectorCheckpoint):
    next_page_url: str | None = None
    last_updated_at: str | None = None
