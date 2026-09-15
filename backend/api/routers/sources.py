"""Source routes: what a Connection synchronizes, and how those runs went."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from api.deps import Caller, Integrations
from api.routers import (
    IngestionSourceUpdate,
    ScheduleInput,
)

router = APIRouter(prefix="/sources", tags=["sources"])
#: Runs across every source in the workspace. A run belongs to a source, but
#: "what is happening right now" is a question about the workspace.
ingestions_router = APIRouter(prefix="/ingestions", tags=["sources"])


@router.get("")
async def list_sources(
    caller: Caller,
    integrations: Integrations,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    integration_connection_id: UUID | None = None,
    target_item_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await integrations.list_sources(
        caller,
        page=page,
        page_size=page_size,
        integration_connection_id=integration_connection_id,
        target_item_id=target_item_id,
        status=status_filter,
    )


@router.get("/{source_id}")
async def get_source(
    source_id: UUID, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    return await integrations.get_source(caller, source_id)


@router.patch("/{source_id}")
async def update_source(
    source_id: UUID,
    body: IngestionSourceUpdate,
    caller: Caller,
    integrations: Integrations,
) -> dict[str, Any]:
    return await integrations.update_source(
        caller, source_id, body.model_dump(exclude_unset=True)
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID, caller: Caller, integrations: Integrations
) -> Response:
    await integrations.delete_source(caller, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{source_id}/status")
async def get_source_status(
    source_id: UUID, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    """The source's own health, and separately the state of its last run."""

    return await integrations.get_source_status(caller, source_id)


@router.post("/{source_id}/ingestions", status_code=status.HTTP_202_ACCEPTED)
async def start_source_ingestion(
    source_id: UUID, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    return await integrations.ingest_source(caller, source_id)


@router.get("/{source_id}/ingestions")
async def list_source_ingestions(
    source_id: UUID,
    caller: Caller,
    integrations: Integrations,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await integrations.list_source_workflows(
        caller, source_id, page=page, page_size=page_size, status=status_filter
    )


@router.get("/{source_id}/ingestions/{workflow_id}")
async def get_source_ingestion(
    source_id: UUID,
    workflow_id: str,
    caller: Caller,
    integrations: Integrations,
) -> dict[str, Any]:
    return await integrations.get_source_workflow(caller, source_id, workflow_id)


@router.get("/{source_id}/schedule")
async def get_source_schedule(
    source_id: UUID, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    return await integrations.get_source_schedule(caller, source_id)


@router.put("/{source_id}/schedule")
async def set_source_schedule(
    source_id: UUID,
    body: ScheduleInput,
    caller: Caller,
    integrations: Integrations,
) -> dict[str, Any]:
    return await integrations.set_source_schedule(caller, source_id, body.model_dump())


@router.delete("/{source_id}/schedule", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_schedule(
    source_id: UUID, caller: Caller, integrations: Integrations
) -> Response:
    await integrations.delete_source_schedule(caller, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/schedule/pause")
async def pause_source_schedule(
    source_id: UUID, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    return await integrations.pause_source_schedule(caller, source_id)


@router.post("/{source_id}/schedule/resume")
async def resume_source_schedule(
    source_id: UUID, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    return await integrations.resume_source_schedule(caller, source_id)


@ingestions_router.get("")
async def list_ingestions(
    caller: Caller,
    integrations: Integrations,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    integration_connection_id: UUID | None = None,
    source_id: UUID | None = None,
) -> dict[str, Any]:
    return await integrations.list_ingestion_jobs(
        caller,
        page=page,
        page_size=page_size,
        status=status_filter,
        integration_connection_id=integration_connection_id,
        source_id=source_id,
    )


@ingestions_router.get("/{workflow_id}")
async def get_ingestion(
    workflow_id: str, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    return await integrations.get_ingestion_job(caller, workflow_id)


@ingestions_router.post("/{workflow_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_ingestion(
    workflow_id: str, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    return await integrations.retry_ingestion_job(caller, workflow_id)


@ingestions_router.post("/{workflow_id}/cancel")
async def cancel_ingestion(
    workflow_id: str, caller: Caller, integrations: Integrations
) -> dict[str, Any]:
    return await integrations.cancel_ingestion_job(caller, workflow_id)


__all__ = ["ingestions_router", "router"]
