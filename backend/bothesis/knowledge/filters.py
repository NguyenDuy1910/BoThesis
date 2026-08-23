"""Permission and scope filters for retrieval requests."""

from __future__ import annotations

from collections.abc import Sequence

from bothesis.document_index.models import ContextualChunk
from bothesis.knowledge.models import RetrievalContext


def reader_ids_for(context: RetrievalContext) -> tuple[str, ...]:
    user = context.user_id.strip().lower()
    values = {"public", user}
    if "@" in user:
        values.add(f"email:{user}")
    values.update(value.strip().lower() for value in context.reader_ids if value.strip())
    values.update(f"external_group:{role.strip().lower()}" for role in context.roles if role.strip())
    return tuple(sorted(values))


def filter_visible_chunks(
    chunks: Sequence[ContextualChunk],
    *,
    context: RetrievalContext,
    reader_ids: tuple[str, ...],
) -> list[ContextualChunk]:
    """Defensively enforce ACL and connector scope before reranking.

    The document index is required to apply the same scope during its search.
    This second check protects downstream rerankers and evidence builders if a
    storage adapter returns an out-of-scope payload.
    """

    allowed_connectors = (
        {str(connector_id) for connector_id in context.connector_ids}
        if context.connector_ids is not None
        else None
    )
    allowed_readers = set(reader_ids)
    visible: list[ContextualChunk] = []
    for chunk in chunks:
        if (
            allowed_connectors is not None
            and chunk.source.connector_id not in allowed_connectors
        ):
            continue
        if not context.is_admin and not allowed_readers.intersection(
            chunk.access.reader_ids
        ):
            continue
        visible.append(chunk)
    return visible


__all__ = ["filter_visible_chunks", "reader_ids_for"]
