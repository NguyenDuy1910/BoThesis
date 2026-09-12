"""Discovery for the deployment-managed Confluence connection."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from config import ConfluenceEnvironmentConfig

from bothesis.connector.confluence._confluence import FinxConfluence
from bothesis.services import (
    SOURCE_MANAGE_PERMISSION,
    AdminExternalUnavailableError,
    AdminValidationError,
    AuthContext,
    require_tenant_permission,
)

_SPACE_KEY = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_PAGE_EXPAND = "space,version"


class ConfluenceEnvironmentService:
    """Inspect a Confluence account that is configured outside the database."""

    def __init__(self, config: ConfluenceEnvironmentConfig) -> None:
        self._config = config

    async def status(self, actor: AuthContext) -> dict[str, Any]:
        require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        if not self._config.configured:
            return {"configured": False, "connected": False}
        try:
            await asyncio.to_thread(self._check)
        except Exception as exc:
            raise AdminExternalUnavailableError(
                "Confluence environment connection validation failed"
            ) from exc
        return {"configured": True, "connected": True}

    async def spaces(self, actor: AuthContext) -> dict[str, Any]:
        require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        client = self._client()
        try:
            values = await asyncio.to_thread(
                lambda: list(client.retrieve_confluence_spaces(limit=100))
            )
        except Exception as exc:
            raise AdminExternalUnavailableError(
                "Confluence spaces could not be loaded"
            ) from exc
        return {
            "spaces": [
                {
                    "key": str(value.get("key") or ""),
                    "name": str(value.get("name") or value.get("key") or ""),
                }
                for value in values
                if value.get("key")
            ]
        }

    async def pages(self, actor: AuthContext, *, space: str) -> dict[str, Any]:
        require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        normalized_space = space.strip()
        if not _SPACE_KEY.fullmatch(normalized_space):
            raise AdminValidationError("Confluence space key is invalid")
        client = self._client()
        try:
            values = await asyncio.to_thread(
                lambda: list(
                    client.paginated_cql_retrieval(
                        f"type=page and space='{normalized_space}'",
                        expand=_PAGE_EXPAND,
                        limit=100,
                    )
                )
            )
        except Exception as exc:
            raise AdminExternalUnavailableError(
                "Confluence pages could not be loaded"
            ) from exc
        return {
            "pages": [
                {
                    "id": str(value.get("id") or ""),
                    "title": str(value.get("title") or "Untitled page"),
                    "space": str(value.get("space", {}).get("key") or normalized_space),
                }
                for value in values
                if value.get("id")
            ]
        }

    def _check(self) -> None:
        list(
            self._client().paginated_cql_retrieval(
                "type=page", expand="version", limit=1
            )
        )

    def _client(self) -> FinxConfluence:
        if not self._config.configured:
            raise AdminValidationError(
                "Set BOTHESIS_CONFLUENCE_BASE_URL, BOTHESIS_CONFLUENCE_USERNAME, "
                "and BOTHESIS_CONFLUENCE_API_TOKEN in backend/.env"
            )
        return FinxConfluence(
            {
                "username": self._config.username,
                "api_token": self._config.api_token,
                "is_cloud": self._config.is_cloud,
            },
            self._config.base_url or "",
            timeout_seconds=self._config.timeout_seconds,
        )


__all__ = ["ConfluenceEnvironmentService"]
