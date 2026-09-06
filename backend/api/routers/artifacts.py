"""Artifact routes: inspect, preview, export, and publish conversation documents."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from api.deps import Artifacts, Caller, Templates
from api.routers import (
    ArtifactContent,
    ArtifactDetail,
    ArtifactExportRequest,
    ArtifactPublishRequest,
    ArtifactPublishResponse,
    TemplateLibraryList,
)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/template-libraries", response_model=TemplateLibraryList)
async def list_template_libraries(
    caller: Caller, templates: Templates
) -> TemplateLibraryList:
    """The template libraries the caller may publish a document into."""

    return TemplateLibraryList(items=await templates.library_collections(caller))


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


@router.post("/{artifact_id}/export", response_model=ArtifactDetail)
async def export_artifact(
    artifact_id: UUID,
    body: ArtifactExportRequest,
    caller: Caller,
    artifacts: Artifacts,
) -> ArtifactDetail:
    return ArtifactDetail.model_validate(
        await artifacts.export(caller, artifact_id, format=body.format)
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
    """Copy the current revision into a template library as a KB document."""

    return ArtifactPublishResponse.model_validate(
        await artifacts.publish(
            caller,
            artifact_id,
            collection_id=body.collection_id,
            title=body.title,
        )
    )
