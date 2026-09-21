"""Ingestion source resources and schedules."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from api.deps import Caller, ConnectionLifecycle
from api.routers import (
    Ingestion,
    IngestionPage,
    Schedule,
    SchedulePatch,
    SchedulePut,
    Source,
    SourcePage,
    SourceStatus,
    SourceUpdate,
)
from api.routers._mapping import ingestion_payload, source_payload
from bothesis.services import ControlPlaneNotFoundError

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=SourcePage)
async def list_sources(
    caller: Caller,
    connections: ConnectionLifecycle,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connection_id: UUID | None = None,
) -> SourcePage:
    value = await connections.list_sources(
        caller,
        page=page,
        page_size=page_size,
        integration_connection_id=connection_id,
    )
    return SourcePage(
        items=[source_payload(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.get("/{source_id}", response_model=Source)
async def get_source(
    source_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> Source:
    return Source.model_validate(
        source_payload(await connections.get_source(caller, source_id))
    )


@router.patch("/{source_id}", response_model=Source)
async def update_source(
    source_id: UUID,
    body: SourceUpdate,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Source:
    return Source.model_validate(
        source_payload(
            await connections.update_source(
                caller, source_id, body.model_dump(exclude_unset=True)
            )
        )
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> Response:
    await connections.delete_source(caller, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{source_id}/status", response_model=SourceStatus)
async def get_source_status(
    source_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> SourceStatus:
    value = await connections.get_source_status(caller, source_id)
    return SourceStatus(
        source_id=source_id,
        source_status=value.get("source_status", "failed"),
        connection_status=value.get("connection_status", "error"),
        latest_ingestion=(
            ingestion_payload(value["workflow"])
            if value.get("workflow")
            else None
        ),
    )


@router.post(
    "/{source_id}/ingestions",
    tags=["ingestions"],
    response_model=Ingestion,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_source_ingestion(
    source_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> Ingestion:
    return Ingestion.model_validate(
        ingestion_payload(await connections.ingest_source(caller, source_id))
    )


@router.get("/{source_id}/ingestions", response_model=IngestionPage, tags=["ingestions"])
async def list_source_ingestions(
    source_id: UUID,
    caller: Caller,
    connections: ConnectionLifecycle,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> IngestionPage:
    value = await connections.list_source_ingestions(
        caller, source_id, page=page, page_size=page_size
    )
    return IngestionPage(
        items=[ingestion_payload(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.get(
    "/{source_id}/ingestions/{ingestion_id}", response_model=Ingestion, tags=["ingestions"]
)
async def get_source_ingestion(
    source_id: UUID,
    ingestion_id: UUID,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Ingestion:
    value = await connections.get_ingestion_by_public_id(caller, ingestion_id)
    if str(value.get("source_id")) != str(source_id):
        raise ControlPlaneNotFoundError(f"ingestion not found: {ingestion_id}")
    return Ingestion.model_validate(ingestion_payload(value))


@router.get("/{source_id}/schedule", response_model=Schedule)
async def get_source_schedule(
    source_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> Schedule:
    return Schedule.model_validate(
        await connections.get_source_schedule(caller, source_id)
    )


@router.put("/{source_id}/schedule", response_model=Schedule)
async def put_source_schedule(
    source_id: UUID,
    body: SchedulePut,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Schedule:
    return Schedule.model_validate(
        await connections.set_source_schedule(
            caller, source_id, body.model_dump()
        )
    )


@router.patch("/{source_id}/schedule", response_model=Schedule)
async def patch_source_schedule(
    source_id: UUID,
    body: SchedulePatch,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Schedule:
    current = await connections.get_source_schedule(caller, source_id)
    current.update(body.model_dump(exclude_unset=True))
    return Schedule.model_validate(
        await connections.set_source_schedule(caller, source_id, current)
    )


@router.delete(
    "/{source_id}/schedule", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_source_schedule(
    source_id: UUID, caller: Caller, connections: ConnectionLifecycle
) -> Response:
    await connections.delete_source_schedule(caller, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
