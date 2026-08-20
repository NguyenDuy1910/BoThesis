"""PostgreSQL fallback storage for bounded raw document binaries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import DocumentBlob

from . import ObjectNotFoundError


class PostgresBlobStorage:
    """Persist raw bytes in ``document_blobs`` within a caller-owned session.

    The calling service must authorize the Document before invoking this
    adapter. Keeping authorization outside this byte store prevents storage
    concerns from depending on document lifecycle services.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(self, document_id: UUID, content: bytes) -> None:
        if not content:
            raise ValueError("raw document bytes must not be empty")
        await self._session.execute(
            insert(DocumentBlob)
            .values(document_id=document_id, raw_bytes=content)
            .on_conflict_do_update(
                index_elements=[DocumentBlob.document_id],
                set_={"raw_bytes": content, "deleted_at": None},
            )
        )
        await self._session.flush()

    async def read(self, document_id: UUID) -> bytes:
        content = await self._session.scalar(
            select(DocumentBlob.raw_bytes).where(
                DocumentBlob.document_id == document_id,
                DocumentBlob.deleted_at.is_(None),
            )
        )
        if content is None:
            raise ObjectNotFoundError("raw document blob was not found")
        return content

    async def soft_delete(self, document_id: UUID) -> None:
        await self._session.execute(
            update(DocumentBlob)
            .where(
                DocumentBlob.document_id == document_id,
                DocumentBlob.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
        )
        await self._session.flush()


__all__ = ["PostgresBlobStorage"]
