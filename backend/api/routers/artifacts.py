"""Artifact routes: inspect, preview, and publish conversation documents."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from api.deps import Artifacts, Caller
from api.routers import (
    ArtifactContent,
    ArtifactDetail,
    ArtifactPublishRequest,
    ArtifactPublishResponse,
)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", response_model=ArtifactDetail)
async def get_artifact(
    artifact_id: UUID, caller: Caller, artifacts: Artifacts
) -> ArtifactDetail:
    return ArtifactDetail.model_validate(await artifacts.get(caller, artifact_id))


@router.get(
    "/{artifact_id}/revisions/{revision}/content", response_model=ArtifactContent
)
async def get_artifact_content(
    artifact_id: UUID, revision: int, caller: Caller, artifacts: Artifacts
) -> ArtifactContent:
    return ArtifactContent.model_validate(
        await artifacts.content(caller, artifact_id, revision=revision)
    )


@router.post(
    "/{artifact_id}/publish",
    response_model=ArtifactPublishResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_artifact(
    artifact_id: UUID,
    body: ArtifactPublishRequest,
    caller: Caller,
    artifacts: Artifacts,
) -> ArtifactPublishResponse:
    """Copy the current revision into a Collection as a KB document."""

    return ArtifactPublishResponse.model_validate(
        await artifacts.publish(
            caller,
            artifact_id,
            collection_id=body.collection_id,
            title=body.title,
        )
    )
