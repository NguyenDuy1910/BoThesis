"""BoThesis API — all route declarations. Implement services in bothesis/*/service.py."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, EmailStr, Field

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

# --- Auth ---


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str
    tenant_id: UUID
    roles: list[str]


# --- Access / RBAC ---


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


class Role(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    permissions: list[str]


class PermissionPatch(BaseModel):
    grant: list[str] = []
    revoke: list[str] = []


class EffectivePermissions(BaseModel):
    user_id: UUID
    permissions: list[str]


# --- Agent / Chat ---


class ThreadCreate(BaseModel):
    title: str | None = None
    metadata: dict[str, Any] = {}


class Thread(BaseModel):
    id: UUID
    user_id: UUID
    title: str | None
    created_at: str
    message_count: int


class MessageSend(BaseModel):
    content: str
    attachments: list[str] = []  # document IDs to ground the answer


class Message(BaseModel):
    id: UUID
    thread_id: UUID
    role: str  # "user" | "assistant"
    content: str
    citations: list[dict[str, Any]] = []
    created_at: str


class ThreadDetail(Thread):
    messages: list[Message]


class ChatHistoryMessage(BaseModel):
    """A prior user or assistant turn retained by the browser conversation store."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)


class ChatRequest(BaseModel):
    """A bounded chat turn submitted by the current WebUI."""

    message: str = Field(min_length=1, max_length=4_000)
    tenant_id: str = Field(min_length=1, max_length=256)
    user_id: str = Field(min_length=1, max_length=256)
    roles: list[str]
    conversation_id: str | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=8)


# --- Connectors ---


class ConnectorCreate(BaseModel):
    type: str  # confluence | jira | slack | pdf | google_drive | database | datalake
    name: str
    config: dict[str, Any]  # provider-specific; secrets resolved server-side


class ConnectorUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class Connector(BaseModel):
    id: UUID
    tenant_id: UUID
    type: str
    name: str
    enabled: bool
    last_synced_at: str | None
    status: str  # idle | syncing | error


class SyncStatus(BaseModel):
    connector_id: UUID
    status: str
    started_at: str | None
    finished_at: str | None
    documents_indexed: int
    error: str | None


# --- Document Index ---


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    connector_ids: list[UUID] | None = None  # None = all permitted sources
    filters: dict[str, Any] = {}


class DocumentResult(BaseModel):
    id: UUID
    connector_id: UUID
    title: str
    excerpt: str
    score: float
    url: str | None
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    results: list[DocumentResult]
    total: int


class DocumentDetail(BaseModel):
    id: UUID
    connector_id: UUID
    title: str
    content: str
    url: str | None
    metadata: dict[str, Any]
    indexed_at: str


# --- Crons ---


class CronCreate(BaseModel):
    name: str
    schedule: str  # cron expression, e.g. "0 2 * * *"
    task: str      # registered task name
    params: dict[str, Any] = {}
    enabled: bool = True


class CronUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None


class CronJob(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    schedule: str
    task: str
    params: dict[str, Any]
    enabled: bool
    last_run_at: str | None
    next_run_at: str | None
    last_status: str | None


class CronRunResult(BaseModel):
    job_id: UUID
    run_id: UUID
    status: str
    started_at: str


# --- BI ---


class BIQueryRequest(BaseModel):
    question: str
    datasource_ids: list[UUID] | None = None
    max_rows: int = 500


class BIQueryResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    explanation: str
    citations: list[dict[str, Any]]


class MetricFilter(BaseModel):
    dimension: str
    operator: str  # eq | in | gt | lt | between
    value: Any


class MetricComputeRequest(BaseModel):
    filters: list[MetricFilter] = []
    group_by: list[str] = []
    date_range: dict[str, str] | None = None


class MetricDefinition(BaseModel):
    id: UUID
    name: str
    description: str
    formula: str
    dimensions: list[str]
    owner: str


class MetricResult(BaseModel):
    metric_id: UUID
    value: Any
    breakdown: list[dict[str, Any]]
    sql: str
    computed_at: str


# ---------------------------------------------------------------------------
# Auth dependency (implement in bothesis/auth/service.py)
# ---------------------------------------------------------------------------


async def get_current_user() -> UserProfile:  # noqa: RUF029
    """Replace with JWT validation + DB lookup."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="auth service not implemented")


# ---------------------------------------------------------------------------
# Auth router
# ---------------------------------------------------------------------------

auth_router = APIRouter(prefix="/auth", tags=["auth"])


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


# ---------------------------------------------------------------------------
# Access / RBAC router
# ---------------------------------------------------------------------------

access_router = APIRouter(prefix="/access", tags=["access"])


@access_router.get("/roles", response_model=list[Role])
async def list_roles(current_user: UserProfile = Depends(get_current_user)) -> list[Role]:
    # return await access_service.list_roles(current_user.tenant_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.post("/roles", response_model=Role, status_code=status.HTTP_201_CREATED)
async def create_role(body: RoleCreate, current_user: UserProfile = Depends(get_current_user)) -> Role:
    # return await access_service.create_role(current_user.tenant_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.get("/roles/{role_id}", response_model=Role)
async def get_role(role_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> Role:
    # return await access_service.get_role(current_user.tenant_id, role_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.put("/roles/{role_id}", response_model=Role)
async def update_role(
    role_id: UUID, body: RoleUpdate, current_user: UserProfile = Depends(get_current_user)
) -> Role:
    # return await access_service.update_role(current_user.tenant_id, role_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@access_router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> None:
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
    user_id: UUID, body: PermissionPatch, current_user: UserProfile = Depends(get_current_user)
) -> EffectivePermissions:
    # return await access_service.patch_permissions(current_user.tenant_id, user_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# Agent / Chat router
# ---------------------------------------------------------------------------

agent_router = APIRouter(prefix="/agent", tags=["agent"])

_agent_loop: Any | None = None


def _get_agent_loop() -> Any:
    """Build the singleton agent loop without introducing a DI framework."""
    global _agent_loop
    if _agent_loop is None:
        from bothesis.agent.tools import ToolRegistry
        from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
        from bothesis.agent.transports.openrouter import OpenRouterTransport
        from bothesis.agent.transports.openrouter_embeddings import (
            OpenRouterEmbeddingClient,
        )
        from bothesis.chat.agent_loop import AgentLoop
        from bothesis.document_index.vector_store import VectorStore
        from bothesis.knowledge.document_index import QdrantSemanticRetriever
        from bothesis.observability import create_langfuse_tracing

        system_prompt = (
            Path(__file__).parent / "bothesis" / "agent" / "prompts" / "system.md"
        ).read_text(encoding="utf-8")
        registry = ToolRegistry()
        retriever = QdrantSemanticRetriever(
            VectorStore.from_environment(timeout=8),
            OpenRouterEmbeddingClient(),
        )
        tracing = create_langfuse_tracing()
        registry.register(KnowledgeSearchTool(retriever, tracing=tracing))
        _agent_loop = AgentLoop(
            transport=OpenRouterTransport(),
            registry=registry,
            system_prompt=system_prompt,
            tracing=tracing,
        )
    return _agent_loop


@agent_router.post("/chat")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Return the agent event stream as server-sent events."""
    from bothesis.agent.models import AgentContext, ConversationMessage

    request_id = uuid4().hex
    context = AgentContext(
        user_id=body.user_id,
        tenant_id=body.tenant_id,
        roles=body.roles,
        conversation_id=body.conversation_id,
        request_id=request_id,
        history=tuple(
            ConversationMessage(role=message.role, content=message.content)
            for message in body.history
        ),
    )
    try:
        loop = _get_agent_loop()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent service is not configured",
        ) from exc
    async def event_gen():
        async for event in loop.run_stream(body.message, context):
            payload = {"type": event.type, **dataclasses.asdict(event)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@agent_router.post("/threads", response_model=Thread, status_code=status.HTTP_201_CREATED)
async def create_thread(body: ThreadCreate, current_user: UserProfile = Depends(get_current_user)) -> Thread:
    # return await agent_service.create_thread(current_user, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@agent_router.get("/threads", response_model=list[Thread])
async def list_threads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserProfile = Depends(get_current_user),
) -> list[Thread]:
    # return await agent_service.list_threads(current_user.id, limit, offset)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@agent_router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> ThreadDetail:
    # return await agent_service.get_thread(current_user, thread_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@agent_router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(thread_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> None:
    # await agent_service.delete_thread(current_user, thread_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@agent_router.post("/threads/{thread_id}/messages", response_model=Message)
async def send_message(
    thread_id: UUID, body: MessageSend, current_user: UserProfile = Depends(get_current_user)
) -> Message:
    """Send a user message and receive a grounded assistant reply (blocking)."""
    # return await agent_service.chat(current_user, thread_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@agent_router.get("/threads/{thread_id}/messages/{message_id}/stream")
async def stream_message(
    thread_id: UUID, message_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> StreamingResponse:
    """SSE stream of an in-progress assistant reply."""
    # async def event_gen():
    #     async for chunk in agent_service.stream(current_user, thread_id, message_id):
    #         yield f"data: {chunk}\n\n"
    # return StreamingResponse(event_gen(), media_type="text/event-stream")
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# Connectors router
# ---------------------------------------------------------------------------

connectors_router = APIRouter(prefix="/connectors", tags=["connectors"])


@connectors_router.get("", response_model=list[Connector])
async def list_connectors(current_user: UserProfile = Depends(get_current_user)) -> list[Connector]:
    # return await connectors_service.list(current_user.tenant_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.post("", response_model=Connector, status_code=status.HTTP_201_CREATED)
async def create_connector(
    body: ConnectorCreate, current_user: UserProfile = Depends(get_current_user)
) -> Connector:
    # return await connectors_service.create(current_user.tenant_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.get("/{connector_id}", response_model=Connector)
async def get_connector(
    connector_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> Connector:
    # return await connectors_service.get(current_user.tenant_id, connector_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.put("/{connector_id}", response_model=Connector)
async def update_connector(
    connector_id: UUID, body: ConnectorUpdate, current_user: UserProfile = Depends(get_current_user)
) -> Connector:
    # return await connectors_service.update(current_user.tenant_id, connector_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> None:
    # await connectors_service.delete(current_user.tenant_id, connector_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.post("/{connector_id}/sync", response_model=SyncStatus, status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    connector_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> SyncStatus:
    """Enqueue a full re-sync for this connector."""
    # return await connectors_service.trigger_sync(current_user.tenant_id, connector_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.get("/{connector_id}/sync/status", response_model=SyncStatus)
async def get_sync_status(
    connector_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> SyncStatus:
    # return await connectors_service.sync_status(current_user.tenant_id, connector_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# Document Index router
# ---------------------------------------------------------------------------

documents_router = APIRouter(prefix="/documents", tags=["documents"])


@documents_router.post("/search", response_model=SearchResponse)
async def search_documents(
    body: SearchRequest, current_user: UserProfile = Depends(get_current_user)
) -> SearchResponse:
    """Permission-filtered semantic search across all indexed sources."""
    # return await document_index_service.search(current_user, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@documents_router.post("/ingest", response_model=DocumentDetail, status_code=status.HTTP_202_ACCEPTED)
async def ingest_document(
    file: UploadFile = File(...), current_user: UserProfile = Depends(get_current_user)
) -> DocumentDetail:
    """Upload and index a file (PDF, DOCX, TXT, …)."""
    # return await document_index_service.ingest(current_user, file)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@documents_router.get("/{doc_id}", response_model=DocumentDetail)
async def get_document(doc_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> DocumentDetail:
    # return await document_index_service.get(current_user, doc_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@documents_router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> None:
    # await document_index_service.delete(current_user, doc_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# Crons router
# ---------------------------------------------------------------------------

crons_router = APIRouter(prefix="/crons", tags=["crons"])


@crons_router.get("", response_model=list[CronJob])
async def list_cron_jobs(current_user: UserProfile = Depends(get_current_user)) -> list[CronJob]:
    # return await crons_service.list(current_user.tenant_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.post("", response_model=CronJob, status_code=status.HTTP_201_CREATED)
async def create_cron_job(body: CronCreate, current_user: UserProfile = Depends(get_current_user)) -> CronJob:
    # return await crons_service.create(current_user.tenant_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.get("/{job_id}", response_model=CronJob)
async def get_cron_job(job_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> CronJob:
    # return await crons_service.get(current_user.tenant_id, job_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.put("/{job_id}", response_model=CronJob)
async def update_cron_job(
    job_id: UUID, body: CronUpdate, current_user: UserProfile = Depends(get_current_user)
) -> CronJob:
    # return await crons_service.update(current_user.tenant_id, job_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron_job(job_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> None:
    # await crons_service.delete(current_user.tenant_id, job_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@crons_router.post("/{job_id}/run", response_model=CronRunResult, status_code=status.HTTP_202_ACCEPTED)
async def run_cron_job_now(job_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> CronRunResult:
    """Trigger an immediate out-of-schedule execution."""
    # return await crons_service.run_now(current_user.tenant_id, job_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# BI router
# ---------------------------------------------------------------------------

bi_router = APIRouter(prefix="/bi", tags=["bi"])


@bi_router.post("/query", response_model=BIQueryResponse)
async def bi_query(body: BIQueryRequest, current_user: UserProfile = Depends(get_current_user)) -> BIQueryResponse:
    """Translate a natural-language question to validated SQL and return results."""
    # return await bi_service.nl_query(current_user, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@bi_router.get("/metrics", response_model=list[MetricDefinition])
async def list_metrics(current_user: UserProfile = Depends(get_current_user)) -> list[MetricDefinition]:
    # return await bi_service.list_metrics(current_user.tenant_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@bi_router.get("/metrics/{metric_id}", response_model=MetricDefinition)
async def get_metric(metric_id: UUID, current_user: UserProfile = Depends(get_current_user)) -> MetricDefinition:
    # return await bi_service.get_metric(current_user.tenant_id, metric_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@bi_router.post("/metrics/{metric_id}/compute", response_model=MetricResult)
async def compute_metric(
    metric_id: UUID, body: MetricComputeRequest, current_user: UserProfile = Depends(get_current_user)
) -> MetricResult:
    """Compute a governed metric with optional dimension filters and date range."""
    # return await bi_service.compute(current_user, metric_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------

app = FastAPI(
    title="BoThesis API",
    version="0.1.0",
    description="Enterprise knowledge and BI assistant.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten per environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_PREFIX = "/api/v1"
app.include_router(auth_router, prefix=_PREFIX)
app.include_router(access_router, prefix=_PREFIX)
app.include_router(agent_router, prefix=_PREFIX)
app.include_router(connectors_router, prefix=_PREFIX)
app.include_router(documents_router, prefix=_PREFIX)
app.include_router(crons_router, prefix=_PREFIX)
app.include_router(bi_router, prefix=_PREFIX)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=os.getenv("BOTHESIS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.getenv("BOTHESIS_PORT", "8000")),
        env_file=Path(__file__).with_name(".env"),
    )
