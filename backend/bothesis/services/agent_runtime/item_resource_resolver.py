"""Resolve authorized Item resources for one agent run."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.agent import ModelContent, ResourceRef
from bothesis.agent.protocol import InputImage
from bothesis.services import (
    AuthContext,
    DocumentNotFoundError,
    DocumentProcessingError,
    StoredFileContent,
)
from bothesis.services.item import ItemService


class ItemResourceResolver:
    """Map stable Item identities to explicit, access-checked capabilities."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        access: AuthContext,
        content: StoredFileContent,
        max_read_characters: int,
    ) -> None:
        if max_read_characters < 1:
            raise ValueError("resource read limit must be greater than zero")
        self._sessions = session_factory
        self._access = access
        self._content = content
        self._max_read_characters = max_read_characters

    async def inspect(self, resource: ResourceRef) -> dict[str, object]:
        item = await self._item(resource)
        return {
            "id": str(item.id),
            "name": str(item.metadata_.get("file_name") or item.title),
            "mime_type": item.mime_type or "application/octet-stream",
            "size_bytes": item.size_bytes,
            "kind": "image" if (item.mime_type or "").startswith("image/") else "file",
            "index_status": item.index_status,
        }

    async def read(self, resource: ResourceRef, *, max_characters: int) -> str:
        if max_characters < 1:
            raise ValueError("resource read limit must be greater than zero")
        item = await self._item(resource)
        if item.upload is not None and item.upload.status != "available":
            raise DocumentProcessingError("resource content is not available")
        canonical = await self._content.canonicalize(item, access=self._access)
        text = canonical.item.get_text_content().strip()
        limit = min(max_characters, self._max_read_characters)
        return text if len(text) <= limit else f"{text[:limit].rstrip()}…"

    async def materialize(self, resource: ResourceRef) -> tuple[ModelContent, ...]:
        item = await self._item(resource)
        mime_type = item.mime_type or ""
        if not mime_type.startswith("image/"):
            raise DocumentProcessingError("resource cannot be materialized as an image")
        image_url = await self._content.direct_file_data(item, expires_seconds=300)
        return (InputImage(image_url=image_url),)

    async def _item(self, resource: ResourceRef):
        try:
            item_id = UUID(resource.id)
        except ValueError as exc:
            raise DocumentNotFoundError("resource not found") from exc
        async with self._sessions() as session:
            return await ItemService(session).get_item(item_id, access=self._access)


__all__ = ["ItemResourceResolver"]
