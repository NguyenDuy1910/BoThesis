"""Deterministic business-filter projection for Qdrant queries."""

from __future__ import annotations

from typing import Any

from qdrant_client import models as qmodels


class VectorStoreFilterBuilder:
    """Translate governed retrieval filters into Qdrant conditions."""

    FILTERABLE_LIST_FIELDS: tuple[str, ...] = (
        "connector_key",
        "document_type",
        "content_type",
        "item_id",
        "chunk_id",
        "section",
        "external_id",
        "parent_item_id",
        "ancestor_ids",
        "collection_item_id",
    )

    @classmethod
    def build_request_filter(cls, request: Any) -> qmodels.Filter:
        # Local import keeps the filter projection independently importable
        # while preserving the existing convenience entry point.
        from bothesis.document_index.vector_store import VectorStore

        return VectorStore.build_retrieval_filter(
            None,
            access_context=getattr(request, "access", None),
            payload_filters=getattr(request, "filters", None),
        )

    @classmethod
    def business_conditions(
        cls,
        filters: Any,
        *,
        field_map: dict[str, str] | None = None,
    ) -> list[Any]:
        conditions: list[Any] = []
        resolved_field_map = {"section": "section_path", **(field_map or {})}
        for logical_name in cls.FILTERABLE_LIST_FIELDS:
            values = getattr(filters, logical_name, [])
            if not values:
                continue
            qdrant_field = resolved_field_map.get(logical_name, logical_name)
            conditions.append(
                qmodels.FieldCondition(
                    key=qdrant_field,
                    match=qmodels.MatchAny(any=values),
                )
            )
        return conditions


__all__ = ["VectorStoreFilterBuilder"]
