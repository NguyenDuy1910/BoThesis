"""Route surface that is declared but not implemented yet.

Every handler here answers 501. They stay in one module so the OpenAPI
contract the WebUI reads is stable while the services behind them are built,
and so no unimplemented route hides among working ones.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from api.routers import (
    BIQueryRequest,
    BIQueryResponse,
    CronCreate,
    CronJob,
    CronRunResult,
    CronUpdate,
    DocumentDetail,
    EffectivePermissions,
    LoginRequest,
    Message,
    MessageSend,
    MetricComputeRequest,
    MetricDefinition,
    MetricResult,
    PermissionPatch,
    RefreshRequest,
    Role,
    RoleCreate,
    RoleUpdate,
    Thread,
    ThreadCreate,
    ThreadDetail,
    TokenResponse,
    UserProfile,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
access_router = APIRouter(prefix="/access", tags=["access"])
threads_router = APIRouter(prefix="/agent", tags=["agent"])
documents_router = APIRouter(prefix="/documents", tags=["documents"])
crons_router = APIRouter(prefix="/crons", tags=["crons"])
bi_router = APIRouter(prefix="/bi", tags=["bi"])


async def get_current_user() -> UserProfile:  # noqa: RUF029
    """Replace with JWT validation + DB lookup."""

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="auth service not implemented",
    )


PLANNED_ROUTERS = (
    auth_router,
    access_router,
    threads_router,
    documents_router,
    crons_router,
    bi_router,
)


@auth_router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    """Validate credentials and issue access + refresh tokens."""
    # from bothesis.auth.service import auth_service
    # return await auth_service.login(body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: UserProfile = Depends(get_current_user)) -> None:
    """Invalidate the current session token."""
    # await auth_service.logout(current_user.id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@auth_router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest) -> TokenResponse:
    """Issue a new access token from a valid refresh token."""
    # return await auth_service.refresh(body.refresh_token)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@auth_router.get("/me", response_model=UserProfile)
async def me(current_user: UserProfile = Depends(get_current_user)) -> UserProfile:
    return current_user


@access_router.get("/roles", response_model=list[Role])
async def list_roles(
    current_user: UserProfile = Depends(get_current_user),
) -> list[Role]:
    # return await access_service.list_roles(current_user.tenant_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.post("/roles", response_model=Role, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate, current_user: UserProfile = Depends(get_current_user)
) -> Role:
    # return await access_service.create_role(current_user.tenant_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.get("/roles/{role_id}", response_model=Role)
async def get_role(
    role_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> Role:
    # return await access_service.get_role(current_user.tenant_id, role_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.put("/roles/{role_id}", response_model=Role)
async def update_role(
    role_id: UUID,
    body: RoleUpdate,
    current_user: UserProfile = Depends(get_current_user),
) -> Role:
    # return await access_service.update_role(current_user.tenant_id, role_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> None:
    # await access_service.delete_role(current_user.tenant_id, role_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.get("/users/{user_id}/permissions", response_model=EffectivePermissions)
async def get_user_permissions(
    user_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> EffectivePermissions:
    # return await access_service.effective_permissions(current_user.tenant_id, user_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.put("/users/{user_id}/permissions", response_model=EffectivePermissions)
async def patch_user_permissions(
    user_id: UUID,
    body: PermissionPatch,
    current_user: UserProfile = Depends(get_current_user),
) -> EffectivePermissions:
    # return await access_service.patch_permissions(current_user.tenant_id, user_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@threads_router.post(
    "/threads", response_model=Thread, status_code=status.HTTP_201_CREATED
)
async def create_thread(
    body: ThreadCreate, current_user: UserProfile = Depends(get_current_user)
) -> Thread:
    # return await agent_service.create_thread(current_user, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@threads_router.get("/threads", response_model=list[Thread])
async def list_threads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserProfile = Depends(get_current_user),
) -> list[Thread]:
    # return await agent_service.list_threads(current_user.id, limit, offset)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@threads_router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(
    thread_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> ThreadDetail:
    # return await agent_service.get_thread(current_user, thread_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@threads_router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> None:
    # await agent_service.delete_thread(current_user, thread_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@threads_router.post("/threads/{thread_id}/messages", response_model=Message)
async def send_message(
    thread_id: UUID,
    body: MessageSend,
    current_user: UserProfile = Depends(get_current_user),
) -> Message:
    """Send a user message and receive a grounded assistant reply (blocking)."""
    # return await agent_service.chat(current_user, thread_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@threads_router.get("/threads/{thread_id}/messages/{message_id}/stream")
async def stream_message(
    thread_id: UUID,
    message_id: UUID,
    current_user: UserProfile = Depends(get_current_user),
) -> StreamingResponse:
    """SSE stream of an in-progress assistant reply."""
    # async def event_gen():
    #     async for chunk in agent_service.stream(current_user, thread_id, message_id):
    #         yield f"data: {chunk}\n\n"
    # return StreamingResponse(event_gen(), media_type="text/event-stream")
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@documents_router.post(
    "/ingest", response_model=DocumentDetail, status_code=status.HTTP_202_ACCEPTED
)
async def ingest_document(
    file: UploadFile = File(...), current_user: UserProfile = Depends(get_current_user)
) -> DocumentDetail:
    """Upload and index a file (PDF, DOCX, TXT, …)."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.get("", response_model=list[CronJob])
async def list_cron_jobs(
    current_user: UserProfile = Depends(get_current_user),
) -> list[CronJob]:
    # return await crons_service.list(current_user.tenant_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.post("", response_model=CronJob, status_code=status.HTTP_201_CREATED)
async def create_cron_job(
    body: CronCreate, current_user: UserProfile = Depends(get_current_user)
) -> CronJob:
    # return await crons_service.create(current_user.tenant_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.get("/{job_id}", response_model=CronJob)
async def get_cron_job(
    job_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> CronJob:
    # return await crons_service.get(current_user.tenant_id, job_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.put("/{job_id}", response_model=CronJob)
async def update_cron_job(
    job_id: UUID,
    body: CronUpdate,
    current_user: UserProfile = Depends(get_current_user),
) -> CronJob:
    # return await crons_service.update(current_user.tenant_id, job_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron_job(
    job_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> None:
    # await crons_service.delete(current_user.tenant_id, job_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.post(
    "/{job_id}/run", response_model=CronRunResult, status_code=status.HTTP_202_ACCEPTED
)
async def run_cron_job_now(
    job_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> CronRunResult:
    """Trigger an immediate out-of-schedule execution."""
    # return await crons_service.run_now(current_user.tenant_id, job_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@bi_router.post("/query", response_model=BIQueryResponse)
async def bi_query(
    body: BIQueryRequest, current_user: UserProfile = Depends(get_current_user)
) -> BIQueryResponse:
    """Translate a natural-language question to validated SQL and return results."""
    # return await bi_service.nl_query(current_user, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@bi_router.get("/metrics", response_model=list[MetricDefinition])
async def list_metrics(
    current_user: UserProfile = Depends(get_current_user),
) -> list[MetricDefinition]:
    # return await bi_service.list_metrics(current_user.tenant_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@bi_router.get("/metrics/{metric_id}", response_model=MetricDefinition)
async def get_metric(
    metric_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> MetricDefinition:
    # return await bi_service.get_metric(current_user.tenant_id, metric_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@bi_router.post("/metrics/{metric_id}/compute", response_model=MetricResult)
async def compute_metric(
    metric_id: UUID,
    body: MetricComputeRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> MetricResult:
    """Compute a governed metric with optional dimension filters and date range."""
    # return await bi_service.compute(current_user, metric_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


