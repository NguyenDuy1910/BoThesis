"""Liveness and dependency health for the running process."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from api.deps import Health
from bothesis.health import HealthReport

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthReport,
    response_model_exclude_none=True,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthReport}},
)
async def health(response: Response, health_service: Health) -> HealthReport:
    report: HealthReport = await health_service.check()
    if report.status == "unhealthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
