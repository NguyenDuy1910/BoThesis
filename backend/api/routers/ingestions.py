"""Workspace ingestion lifecycle resources."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from api.deps import Caller, ConnectionLifecycle
from api.routers import Ingestion, IngestionPage
from api.routers._mapping import ingestion_payload

router = APIRouter(prefix="/ingestions", tags=["ingestions"])


@router.get("", response_model=IngestionPage)
async def list_ingestions(
    caller: Caller,
    connections: ConnectionLifecycle,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    source_id: UUID | None = None,
    connection_id: UUID | None = None,
    status: str | None = None,
) -> IngestionPage:
    value = await connections.list_ingestions(
        caller,
        page=page,
        page_size=page_size,
        source_id=source_id,
        integration_connection_id=connection_id,
        status=status,
    )
    return IngestionPage(
        items=[ingestion_payload(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.get("/{ingestion_id}", response_model=Ingestion)
async def get_ingestion(
    ingestion_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> Ingestion:
    return Ingestion.model_validate(
        ingestion_payload(
            await connections.get_ingestion_by_public_id(caller, ingestion_id)
        )
    )


@router.post("/{ingestion_id}/retry", response_model=Ingestion, status_code=202)
async def retry_ingestion(
    ingestion_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> Ingestion:
    return Ingestion.model_validate(
        ingestion_payload(
            await connections.retry_ingestion_by_public_id(caller, ingestion_id)
        )
    )


@router.post("/{ingestion_id}/cancel", response_model=Ingestion)
async def cancel_ingestion(
    ingestion_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> Ingestion:
    return Ingestion.model_validate(
        ingestion_payload(
            await connections.cancel_ingestion_by_public_id(caller, ingestion_id)
        )
    )


__all__ = ["router"]
