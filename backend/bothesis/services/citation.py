"""Canonical citation persistence for indexed document chunks."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.connector.protocol import Chunk, CitationInfo, CitationSpan
from bothesis.db.models import Citation


class CitationService:
    """Replace and resolve canonical citation geometry by Item and chunk ID."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_item(
        self,
        item_id: UUID,
        chunks: Sequence[Chunk],
    ) -> None:
        rows = self._rows(item_id, chunks)
        await self._session.execute(
            update(Citation)
            .where(Citation.item_id == item_id, Citation.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        if not rows:
            return

        statement = insert(Citation).values(rows)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[Citation.item_id, Citation.chunk_id],
                set_={
                    "section_path": statement.excluded.section_path,
                    "anchor": statement.excluded.anchor,
                    "page_start": statement.excluded.page_start,
                    "page_end": statement.excluded.page_end,
                    "spans": statement.excluded.spans,
                    "deleted_at": None,
                    "updated_at": func.now(),
                },
            )
        )

    async def get(self, item_id: UUID, chunk_id: str) -> CitationInfo | None:
        citations = await self.get_for_chunks(item_id, [chunk_id])
        return citations.get(chunk_id.strip())

    async def get_for_chunks(
        self,
        item_id: UUID,
        chunk_ids: Sequence[str],
    ) -> dict[str, CitationInfo]:
        normalized_ids = tuple(
            dict.fromkeys(
                chunk_id.strip()
                for chunk_id in chunk_ids
                if isinstance(chunk_id, str) and chunk_id.strip()
            )
        )
        if not normalized_ids:
            return {}
        rows = await self._session.scalars(
            select(Citation).where(
                Citation.item_id == item_id,
                Citation.chunk_id.in_(normalized_ids),
                Citation.deleted_at.is_(None),
            )
        )
        return {row.chunk_id: self._citation(row) for row in rows}

    @staticmethod
    def _rows(item_id: UUID, chunks: Sequence[Chunk]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for chunk in chunks:
            if chunk.item_id != str(item_id):
                raise ValueError(
                    f"Chunk {chunk.id!r} belongs to item {chunk.item_id!r}, "
                    f"not {item_id!s}"
                )
            chunk_id = chunk.id.strip()
            if chunk_id in seen_ids:
                raise ValueError(f"Duplicate citation chunk ID {chunk_id!r}")
            seen_ids.add(chunk_id)
            section_path = _section_path(chunk)
            page_start, page_end = _page_range(chunk.citation)
            rows.append(
                {
                    "id": uuid4(),
                    "item_id": item_id,
                    "chunk_id": chunk_id,
                    "section_path": section_path,
                    "anchor": _text(chunk.citation.anchor),
                    "page_start": page_start,
                    "page_end": page_end,
                    "spans": [
                        span.model_dump(mode="json", exclude_none=True)
                        for span in chunk.citation.spans
                    ],
                }
            )
        return rows

    @staticmethod
    def _citation(row: Citation) -> CitationInfo:
        section_path = tuple(row.section_path)
        return CitationInfo(
            section=section_path[-1] if section_path else None,
            section_path=section_path,
            anchor=row.anchor,
            page_start=row.page_start,
            page_end=row.page_end,
            spans=tuple(CitationSpan.model_validate(span) for span in row.spans),
        )


def _section_path(chunk: Chunk) -> list[str]:
    if chunk.section_path:
        return [part.strip() for part in chunk.section_path if part.strip()]
    if chunk.citation.section_path:
        return [part.strip() for part in chunk.citation.section_path if part.strip()]
    section = _text(chunk.citation.section)
    return [section] if section is not None else []


def _page_range(citation: CitationInfo) -> tuple[int | None, int | None]:
    pages = [span.page for span in citation.spans if span.page is not None]
    return (
        citation.page_start if citation.page_start is not None else min(pages, default=None),
        citation.page_end if citation.page_end is not None else max(pages, default=None),
    )


def _text(value: str | None) -> str | None:
    normalized = value.strip() if isinstance(value, str) else ""
    return normalized or None


__all__ = ["CitationService"]
