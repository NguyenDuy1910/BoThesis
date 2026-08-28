"""BoThesis HTTP boundary and complete FastAPI route surface."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from dotenv import load_dotenv
from bothesis.connector.protocol import BoundingBox, CitationInfo
from bothesis.document_index.raw_storage import ObjectStorageError
from bothesis.health import HealthReport, HealthService, HealthSettings
from bothesis.services import (
    AdminApiService,
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    ApiService,
    AuthServiceError,
    AuthorizationError,
    DocumentNotFoundError,
    IdentityInactiveError,
    IdentityNotFoundError,
    RequestIdentity,
    UploadConflictError,
    UploadTooLargeError,
    UploadValidationError,
)

if __name__ == "__main__":
    load_dotenv(Path(__file__).with_name(".env"), override=False)

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
    content: str = Field(min_length=1, max_length=8_000)


class ChatRequest(BaseModel):
    """A bounded chat turn submitted by the current WebUI."""

    message: str = Field(min_length=1, max_length=4_000)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=256)
    user_id: str | None = Field(default=None, min_length=1, max_length=256)
    roles: list[str] = Field(default_factory=list, deprecated=True)
    conversation_id: UUID | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=24)
    knowledge_mode: Literal["auto", "selected", "off"] = "auto"
    collection_item_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_collection_selection(self) -> ChatRequest:
        if self.knowledge_mode == "selected" and not self.collection_item_ids:
            raise ValueError("selected knowledge mode requires at least one Collection")
        if self.knowledge_mode != "selected" and self.collection_item_ids:
            raise ValueError("Collection IDs are only accepted in selected mode")
        if len(self.collection_item_ids) != len(set(self.collection_item_ids)):
            raise ValueError("Collection IDs must be unique")
        return self


class DocumentUploadStartRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=160)
    size_bytes: int = Field(ge=1)


class DocumentUploadTarget(BaseModel):
    mode: Literal["presigned"]
    url: str
    method: str
    headers: dict[str, str]
    expires_at: str


class DocumentMetadata(BaseModel):
    id: str
    parent_item_id: str | None = None
    file_name: str
    content_type: str
    size_bytes: int
    status: Literal["pending", "processing", "ready", "failed", "unsupported"]
    indexed: bool = False
    upload_status: Literal["pending", "available", "failed"] | None = None
    created_at: str
    uploaded_at: str | None = None


class DocumentUploadStartResponse(BaseModel):
    upload_required: bool
    target: DocumentUploadTarget | None = None
    document: DocumentMetadata


class CollectionDocumentUploadResponse(BaseModel):
    document: DocumentMetadata
    ingestion_status: Literal["ready", "failed"]
    created: bool


# --- Document Index ---


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    collection_item_ids: list[UUID] | None = None
    filters: dict[str, Any] = {}


class DocumentResult(BaseModel):
    id: UUID
    collection_item_id: UUID
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
    collection_item_id: UUID
    title: str
    content: str
    url: str | None
    metadata: dict[str, Any]
    indexed_at: str


class ViewerElement(BaseModel):
    element_id: str
    text: str
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    section_path: list[str] = Field(default_factory=list)
    anchor: str | None = None
    bounding_box: BoundingBox | None = None


class ViewerFocus(BaseModel):
    chunk_id: str
    chunk_text: str
    citation: CitationInfo


class KnowledgeItemViewer(BaseModel):
    item_id: str
    title: str
    content_type: str
    external_url: str | None = None
    document_url: str | None = None
    elements: list[ViewerElement]
    focus: ViewerFocus | None = None


class KnowledgeCitationResponse(BaseModel):
    """A permission-checked citation resolved at click time."""

    item_id: str
    chunk_id: str
    title: str
    content_type: str
    document_url: str | None = None
    external_url: str | None = None
    citation: CitationInfo


# --- Crons ---


class CronCreate(BaseModel):
    name: str
    schedule: str  # cron expression, e.g. "0 2 * * *"
    task: str  # registered task name
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


# --- Admin ---


class AdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpaceUpdate(AdminRequest):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    settings: dict[str, Any] | None = None


class UserCreate(AdminRequest):
    email: EmailStr
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role_id: UUID
    group_ids: list[UUID] = Field(default_factory=list)


class UserUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role_id: UUID | None = None
    status: Literal["active", "inactive"] | None = None
    group_ids: list[UUID] | None = None


class AdminRoleCreate(AdminRequest):
    code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    permission_codes: list[str] = Field(default_factory=list)


class AdminRoleUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    permission_codes: list[str] | None = None
    status: Literal["active", "inactive"] | None = None


class GroupCreate(AdminRequest):
    code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=2_000)


class GroupUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=2_000)
    status: Literal["active", "inactive"] | None = None


class GroupMembersUpdate(AdminRequest):
    user_ids: list[UUID]


class PluginConnectionCreate(AdminRequest):
    plugin_key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = Field(default=None, repr=False)
    credential_type: str | None = Field(default=None, min_length=1, max_length=64)
    owner_type: Literal["user", "tenant"] = "tenant"


class PluginConnectionUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = Field(default=None, repr=False)
    credential_type: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["draft", "active", "disabled", "error"] | None = None


class ScheduleInput(AdminRequest):
    schedule_type: Literal["cron", "interval"] = "cron"
    cron_expression: str = Field(min_length=1, max_length=255)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool = True
    overlap_policy: Literal["skip", "queue", "replace"] = "skip"


class PluginBindingCreate(AdminRequest):
    target_item_id: UUID
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    schedule: ScheduleInput | None = None


class PluginBindingUpdate(AdminRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    status: Literal["active", "disabled", "error"] | None = None
    schedule: ScheduleInput | None = None
    clear_schedule: bool = False


class ItemStatusUpdate(AdminRequest):
    status: Literal["pending", "processing", "ready", "failed", "unsupported"]


class CollectionCreate(AdminRequest):
    title: str = Field(min_length=1, max_length=255)
    parent_item_id: UUID | None = None
    inherit_access: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectionUpdate(AdminRequest):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2_000)


class AccessRequestCreate(AdminRequest):
    requester_user_id: UUID
    collection_item_id: UUID
    requested_role: Literal["owner", "editor", "viewer"] = "viewer"
    reason: str | None = Field(default=None, min_length=1, max_length=4_000)


class AccessRequestDecision(AdminRequest):
    decision: Literal["approved", "denied"]
    review_note: str | None = Field(default=None, min_length=1, max_length=4_000)


class CollectionAccessGrant(AdminRequest):
    principal_type: Literal["user", "group"]
    principal_id: UUID
    role: Literal["owner", "editor", "viewer"]


# ---------------------------------------------------------------------------
# Auth dependency (implement in bothesis/auth/service.py)
# ---------------------------------------------------------------------------


async def get_current_user() -> UserProfile:  # noqa: RUF029
    """Replace with JWT validation + DB lookup."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="auth service not implemented",
    )


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


# ---------------------------------------------------------------------------
# Agent / Chat router
# ---------------------------------------------------------------------------

agent_router = APIRouter(prefix="/agent", tags=["agent"])

_INSECURE_DEVELOPMENT_IDENTITY_ENV = "BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY"


def _environment_boolean(name: str, *, default: bool = False) -> bool:
    """Read one strict JSON boolean at the application composition boundary."""

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be a JSON boolean") from exc
    if not isinstance(value, bool):
        raise RuntimeError(f"{name} must be a JSON boolean")
    return value


_allow_insecure_development_identity = _environment_boolean(
    _INSECURE_DEVELOPMENT_IDENTITY_ENV
)
_api_service = ApiService(
    allow_insecure_development_identity=_allow_insecure_development_identity,
    qdrant_prefer_grpc=_environment_boolean("QDRANT_PREFER_GRPC"),
    contextualization_enabled=_environment_boolean(
        "BOTHESIS_CONTEXTUALIZATION_ENABLED"
    ),
    contextualization_model=os.getenv("BOTHESIS_CONTEXTUALIZATION_MODEL") or None,
    hybrid_candidate_limit=int(
        os.getenv("BOTHESIS_HYBRID_CANDIDATE_LIMIT", "20")
    ),
)
_admin_service = AdminApiService(
    allow_insecure_development_identity=_allow_insecure_development_identity
)


def _request_identity(request: Request) -> RequestIdentity:
    auth_context = getattr(request.state, "auth_context", None)
    return RequestIdentity(
        auth_context=auth_context,
        user_id=request.headers.get("X-Bothesis-User-Id"),
        tenant_id=request.headers.get("X-Bothesis-Tenant-Id"),
    )


@agent_router.post("/chat")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    events = await _api_service.chat_events(
        _request_identity(request),
        message=body.message,
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        conversation_id=body.conversation_id,
        history=[(message.role, message.content) for message in body.history],
        knowledge_mode=body.knowledge_mode,
        collection_item_ids=body.collection_item_ids,
        is_disconnected=request.is_disconnected,
    )
    return StreamingResponse(
        (f"data: {event}\n\n" async for event in events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@agent_router.get("/collections")
async def list_chat_collections(request: Request) -> dict[str, Any]:
    return await _api_service.list_chat_collections(_request_identity(request))


@agent_router.post(
    "/threads", response_model=Thread, status_code=status.HTTP_201_CREATED
)
async def create_thread(
    body: ThreadCreate, current_user: UserProfile = Depends(get_current_user)
) -> Thread:
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
async def get_thread(
    thread_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> ThreadDetail:
    # return await agent_service.get_thread(current_user, thread_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@agent_router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> None:
    # await agent_service.delete_thread(current_user, thread_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@agent_router.post("/threads/{thread_id}/messages", response_model=Message)
async def send_message(
    thread_id: UUID,
    body: MessageSend,
    current_user: UserProfile = Depends(get_current_user),
) -> Message:
    """Send a user message and receive a grounded assistant reply (blocking)."""
    # return await agent_service.chat(current_user, thread_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@agent_router.get("/threads/{thread_id}/messages/{message_id}/stream")
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


# ---------------------------------------------------------------------------
# Document Index router
# ---------------------------------------------------------------------------

knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@knowledge_router.get(
    "/items/{item_id:path}/citations/{chunk_id:path}",
    response_model=KnowledgeCitationResponse,
)
async def get_knowledge_citation(
    item_id: str,
    chunk_id: str,
    request: Request,
) -> KnowledgeCitationResponse:
    return KnowledgeCitationResponse.model_validate(
        await _api_service.get_knowledge_citation(
            _request_identity(request),
            item_id=item_id,
            chunk_id=chunk_id,
        )
    )


@knowledge_router.get(
    "/items/{item_id:path}",
    response_model=KnowledgeItemViewer,
)
async def get_knowledge_item_viewer(
    item_id: str,
    request: Request,
    chunk: str | None = Query(default=None, min_length=1, max_length=512),
) -> KnowledgeItemViewer:
    return KnowledgeItemViewer.model_validate(
        await _api_service.get_knowledge_item(
            _request_identity(request),
            item_id=item_id,
            chunk_id=chunk,
        )
    )


documents_router = APIRouter(prefix="/documents", tags=["documents"])
collections_router = APIRouter(prefix="/collections", tags=["collections"])


@collections_router.post(
    "/{collection_id}/documents/upload",
    response_model=CollectionDocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_collection_document(
    collection_id: UUID,
    request: Request,
    file: Annotated[UploadFile, File(...)],
    idempotency_key: Annotated[
        str,
        Header(min_length=1, max_length=128, alias="Idempotency-Key"),
    ],
) -> CollectionDocumentUploadResponse:
    return CollectionDocumentUploadResponse.model_validate(
        await _api_service.upload_collection_document(
            _request_identity(request),
            collection_id,
            idempotency_key=idempotency_key,
            file_name=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            content=file,
        )
    )


@documents_router.post(
    "/uploads",
    response_model=DocumentUploadStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_document_upload(
    body: DocumentUploadStartRequest,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=128,
        alias="Idempotency-Key",
    ),
) -> DocumentUploadStartResponse:
    return DocumentUploadStartResponse.model_validate(
        await _api_service.start_document_upload(
            _request_identity(request),
            idempotency_key=idempotency_key,
            file_name=body.file_name,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    )


@documents_router.post(
    "/{document_id}/complete",
    response_model=DocumentMetadata,
)
async def complete_document_upload(
    document_id: UUID,
    request: Request,
) -> DocumentMetadata:
    return DocumentMetadata.model_validate(
        await _api_service.complete_document_upload(
            _request_identity(request),
            document_id,
        )
    )


@documents_router.post(
    "/{document_id}/retry",
    response_model=CollectionDocumentUploadResponse,
)
async def retry_document_indexing(
    document_id: UUID,
    request: Request,
) -> CollectionDocumentUploadResponse:
    return CollectionDocumentUploadResponse.model_validate(
        await _api_service.retry_document_indexing(
            _request_identity(request),
            document_id,
        )
    )


@documents_router.post("/search", response_model=SearchResponse)
async def search_documents(
    body: SearchRequest, current_user: UserProfile = Depends(get_current_user)
) -> SearchResponse:
    """Permission-filtered semantic search across all indexed sources."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@documents_router.post(
    "/ingest", response_model=DocumentDetail, status_code=status.HTTP_202_ACCEPTED
)
async def ingest_document(
    file: UploadFile = File(...), current_user: UserProfile = Depends(get_current_user)
) -> DocumentDetail:
    """Upload and index a file (PDF, DOCX, TXT, …)."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@documents_router.get("/{doc_id}", response_model=DocumentMetadata)
async def get_document(
    doc_id: UUID,
    request: Request,
) -> DocumentMetadata:
    return DocumentMetadata.model_validate(
        await _api_service.get_document(_request_identity(request), doc_id)
    )


@documents_router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    request: Request,
) -> None:
    await _api_service.delete_document(_request_identity(request), doc_id)


# ---------------------------------------------------------------------------
# Crons router
# ---------------------------------------------------------------------------

crons_router = APIRouter(prefix="/crons", tags=["crons"])


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


# ---------------------------------------------------------------------------
# BI router
# ---------------------------------------------------------------------------

bi_router = APIRouter(prefix="/bi", tags=["bi"])


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


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

admin_router = APIRouter(prefix="/admin", tags=["admin"])
AdminIdentity = Annotated[RequestIdentity, Depends(_request_identity)]


@admin_router.get("/overview")
async def admin_overview(identity: AdminIdentity) -> dict[str, Any]:
    return await _admin_service.overview(identity)


@admin_router.get("/spaces")
async def admin_list_spaces(identity: AdminIdentity) -> dict[str, Any]:
    return await _admin_service.list_spaces(identity)


@admin_router.get("/spaces/{tenant_id}")
async def admin_get_space(
    tenant_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_space(identity, tenant_id)


@admin_router.patch("/spaces/{tenant_id}")
async def admin_update_space(
    tenant_id: UUID, body: SpaceUpdate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.update_space(
        identity, tenant_id, body.model_dump(exclude_unset=True)
    )


@admin_router.get("/users")
async def admin_list_users(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    role_id: UUID | None = None,
    sort: str = "name",
    direction: str = "asc",
) -> dict[str, Any]:
    return await _admin_service.list_users(
        identity,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        role_id=role_id,
        sort=sort,
        direction=direction,
    )


@admin_router.post("/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    body: UserCreate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.create_user(identity, body.model_dump())


@admin_router.get("/users/{user_id}")
async def admin_get_user(
    user_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_user(identity, user_id)


@admin_router.patch("/users/{user_id}")
async def admin_update_user(
    user_id: UUID, body: UserUpdate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.update_user(
        identity, user_id, body.model_dump(exclude_unset=True)
    )


@admin_router.get("/permissions")
async def admin_list_permissions(identity: AdminIdentity) -> dict[str, Any]:
    return await _admin_service.list_permissions(identity)


@admin_router.get("/roles")
async def admin_list_roles(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await _admin_service.list_roles(
        identity,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@admin_router.post("/roles", status_code=status.HTTP_201_CREATED)
async def admin_create_role(
    body: AdminRoleCreate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.create_role(identity, body.model_dump())


@admin_router.get("/roles/{role_id}")
async def admin_get_role(
    role_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_role(identity, role_id)


@admin_router.patch("/roles/{role_id}")
async def admin_update_role(
    role_id: UUID, body: AdminRoleUpdate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.update_role(
        identity, role_id, body.model_dump(exclude_unset=True)
    )


@admin_router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_disable_role(role_id: UUID, identity: AdminIdentity) -> Response:
    await _admin_service.disable_role(identity, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/groups")
async def admin_list_groups(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await _admin_service.list_groups(
        identity,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@admin_router.post("/groups", status_code=status.HTTP_201_CREATED)
async def admin_create_group(
    body: GroupCreate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.create_group(identity, body.model_dump())


@admin_router.get("/groups/{group_id}")
async def admin_get_group(
    group_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_group(identity, group_id)


@admin_router.patch("/groups/{group_id}")
async def admin_update_group(
    group_id: UUID, body: GroupUpdate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.update_group(
        identity, group_id, body.model_dump(exclude_unset=True)
    )


@admin_router.put("/groups/{group_id}/members")
async def admin_replace_group_members(
    group_id: UUID, body: GroupMembersUpdate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.replace_group_members(
        identity, group_id, body.user_ids
    )


@admin_router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_group(
    group_id: UUID, identity: AdminIdentity
) -> Response:
    await _admin_service.delete_group(identity, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/plugins/capabilities")
async def admin_plugin_capabilities(identity: AdminIdentity) -> dict[str, Any]:
    return await _admin_service.plugin_capabilities(identity)


@admin_router.get("/plugin-connections")
async def admin_list_plugin_connections(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    plugin_key: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await _admin_service.list_plugin_connections(
        identity,
        page=page,
        page_size=page_size,
        search=search,
        plugin_key=plugin_key,
        status=status_filter,
    )


@admin_router.post("/plugin-connections", status_code=status.HTTP_201_CREATED)
async def admin_create_plugin_connection(
    body: PluginConnectionCreate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.create_plugin_connection(identity, body.model_dump())


@admin_router.get("/plugin-connections/{connection_id}")
async def admin_get_plugin_connection(
    connection_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_plugin_connection(identity, connection_id)


@admin_router.patch("/plugin-connections/{connection_id}")
async def admin_update_plugin_connection(
    connection_id: UUID,
    body: PluginConnectionUpdate,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.update_plugin_connection(
        identity, connection_id, body.model_dump(exclude_unset=True)
    )


@admin_router.delete(
    "/plugin-connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_plugin_connection(
    connection_id: UUID, identity: AdminIdentity
) -> Response:
    await _admin_service.delete_plugin_connection(identity, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post("/plugin-connections/{connection_id}/validate")
async def admin_validate_plugin_connection(
    connection_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.validate_plugin_connection(identity, connection_id)


@admin_router.get("/plugin-bindings")
async def admin_list_plugin_bindings(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connection_id: UUID | None = None,
    target_item_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await _admin_service.list_plugin_bindings(
        identity,
        page=page,
        page_size=page_size,
        connection_id=connection_id,
        target_item_id=target_item_id,
        status=status_filter,
    )


@admin_router.post(
    "/plugin-connections/{connection_id}/bindings",
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_plugin_binding(
    connection_id: UUID,
    body: PluginBindingCreate,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.create_plugin_binding(
        identity, connection_id, body.model_dump()
    )


@admin_router.get("/plugin-bindings/{binding_id}")
async def admin_get_plugin_binding(
    binding_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_plugin_binding(identity, binding_id)


@admin_router.patch("/plugin-bindings/{binding_id}")
async def admin_update_plugin_binding(
    binding_id: UUID,
    body: PluginBindingUpdate,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.update_plugin_binding(
        identity, binding_id, body.model_dump(exclude_unset=True)
    )


@admin_router.delete(
    "/plugin-bindings/{binding_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def admin_delete_plugin_binding(
    binding_id: UUID, identity: AdminIdentity
) -> Response:
    await _admin_service.delete_plugin_binding(identity, binding_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post(
    "/plugin-bindings/{binding_id}/sync", status_code=status.HTTP_202_ACCEPTED
)
async def admin_sync_plugin_binding(
    binding_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.sync_plugin_binding(identity, binding_id)


@admin_router.get("/plugin-bindings/{binding_id}/workflows")
async def admin_list_binding_workflows(
    binding_id: UUID,
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await _admin_service.list_binding_workflows(
        identity,
        binding_id,
        page=page,
        page_size=page_size,
        status=status_filter,
    )


@admin_router.get("/plugin-bindings/{binding_id}/workflows/{workflow_id}")
async def admin_get_binding_workflow(
    binding_id: UUID,
    workflow_id: str,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.get_binding_workflow(
        identity, binding_id, workflow_id
    )


@admin_router.get("/plugin-bindings/{binding_id}/status")
async def admin_get_binding_status(
    binding_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_binding_status(identity, binding_id)


@admin_router.get("/plugin-bindings/{binding_id}/schedule")
async def admin_get_binding_schedule(
    binding_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_binding_schedule(identity, binding_id)


@admin_router.put("/plugin-bindings/{binding_id}/schedule")
async def admin_set_binding_schedule(
    binding_id: UUID,
    body: ScheduleInput,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.set_binding_schedule(
        identity, binding_id, body.model_dump()
    )


@admin_router.delete(
    "/plugin-bindings/{binding_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_binding_schedule(
    binding_id: UUID, identity: AdminIdentity
) -> Response:
    await _admin_service.delete_binding_schedule(identity, binding_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post("/plugin-bindings/{binding_id}/schedule/pause")
async def admin_pause_binding_schedule(
    binding_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.pause_binding_schedule(identity, binding_id)


@admin_router.post("/plugin-bindings/{binding_id}/schedule/resume")
async def admin_resume_binding_schedule(
    binding_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.resume_binding_schedule(identity, binding_id)


@admin_router.get("/ingestion/jobs")
async def admin_list_ingestion_jobs(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    connection_id: UUID | None = None,
    binding_id: UUID | None = None,
) -> dict[str, Any]:
    return await _admin_service.list_ingestion_jobs(
        identity,
        page=page,
        page_size=page_size,
        status=status_filter,
        connection_id=connection_id,
        binding_id=binding_id,
    )


@admin_router.get("/ingestion/jobs/{workflow_id}")
async def admin_get_ingestion_job(
    workflow_id: str, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_ingestion_job(identity, workflow_id)


@admin_router.post(
    "/ingestion/jobs/{workflow_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
)
async def admin_retry_ingestion_job(
    workflow_id: str, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.retry_ingestion_job(identity, workflow_id)


@admin_router.post("/ingestion/jobs/{workflow_id}/cancel")
async def admin_cancel_ingestion_job(
    workflow_id: str, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.cancel_ingestion_job(identity, workflow_id)


@admin_router.get("/items")
async def admin_list_items(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    item_type: str | None = None,
    binding_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
    sort: str = "updated_at",
    direction: str = "desc",
) -> dict[str, Any]:
    return await _admin_service.list_items(
        identity,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        item_type=item_type,
        binding_id=binding_id,
        created_by_user_id=created_by_user_id,
        sort=sort,
        direction=direction,
    )


@admin_router.post("/collections", status_code=status.HTTP_201_CREATED)
async def admin_create_collection(
    body: CollectionCreate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.create_collection(identity, body.model_dump())


@admin_router.patch("/collections/{item_id}")
async def admin_update_collection(
    item_id: UUID,
    body: CollectionUpdate,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.update_collection(
        identity,
        item_id,
        body.model_dump(exclude_unset=True),
    )


@admin_router.get("/items/{item_id}")
async def admin_get_item(
    item_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_item(identity, item_id)


@admin_router.patch("/items/{item_id}")
async def admin_update_item(
    item_id: UUID,
    body: ItemStatusUpdate,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.update_item(
        identity, item_id, body.status
    )


@admin_router.post(
    "/items/{item_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
)
async def admin_retry_item(
    item_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.retry_item(identity, item_id)


@admin_router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_item(
    item_id: UUID, identity: AdminIdentity
) -> Response:
    await _admin_service.delete_item(identity, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/access-requests")
async def admin_list_access_requests(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await _admin_service.list_access_requests(
        identity,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )


@admin_router.post("/access-requests", status_code=status.HTTP_201_CREATED)
async def admin_create_access_request(
    body: AccessRequestCreate, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.create_access_request(identity, body.model_dump())


@admin_router.get("/access-requests/{request_id}")
async def admin_get_access_request(
    request_id: UUID, identity: AdminIdentity
) -> dict[str, Any]:
    return await _admin_service.get_access_request(identity, request_id)


@admin_router.post("/access-requests/{request_id}/decision")
async def admin_decide_access_request(
    request_id: UUID,
    body: AccessRequestDecision,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.decide_access_request(
        identity, request_id, body.model_dump()
    )


@admin_router.get("/collections/{item_id}/access")
async def admin_list_collection_access(
    item_id: UUID,
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict[str, Any]:
    return await _admin_service.list_collection_access(
        identity, item_id, page=page, page_size=page_size
    )


@admin_router.put("/collections/{item_id}/access")
async def admin_grant_collection_access(
    item_id: UUID,
    body: CollectionAccessGrant,
    identity: AdminIdentity,
) -> dict[str, Any]:
    return await _admin_service.grant_collection_access(
        identity, item_id, body.model_dump()
    )


@admin_router.delete(
    "/collections/{item_id}/access/{principal_type}/{principal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_revoke_collection_access(
    item_id: UUID,
    principal_type: Literal["user", "group"],
    principal_id: UUID,
    identity: AdminIdentity,
) -> Response:
    await _admin_service.revoke_collection_access(
        identity,
        item_id,
        principal_type=principal_type,
        principal_id=principal_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/audit-logs")
async def admin_list_audit_logs(
    identity: AdminIdentity,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    return await _admin_service.list_audit_logs(
        identity,
        page=page,
        page_size=page_size,
        search=search,
        action=action,
        resource_type=resource_type,
    )


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    try:
        yield
    finally:
        await _api_service.aclose()


app = FastAPI(
    title="BoThesis API",
    version="0.1.0",
    description="Enterprise knowledge and BI assistant.",
    lifespan=_app_lifespan,
)
app.state.allow_insecure_development_identity = _allow_insecure_development_identity


async def _service_error(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, (AdminNotFoundError, IdentityNotFoundError, DocumentNotFoundError)):
        status_code = status.HTTP_404_NOT_FOUND
        detail = str(exc)
    elif isinstance(exc, (AdminConflictError, UploadConflictError)):
        status_code = status.HTTP_409_CONFLICT
        detail = str(exc)
    elif isinstance(exc, (AdminValidationError, UploadValidationError)):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = str(exc)
    elif isinstance(exc, UploadTooLargeError):
        status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        detail = str(exc)
    elif isinstance(exc, AuthorizationError):
        detail = str(exc)
        status_code = (
            status.HTTP_401_UNAUTHORIZED
            if any(
                marker in detail
                for marker in (
                    "authenticated request context",
                    "development user ID",
                    "request auth context",
                )
            )
            else status.HTTP_403_FORBIDDEN
        )
    elif isinstance(exc, (IdentityInactiveError, AuthServiceError)):
        status_code = status.HTTP_401_UNAUTHORIZED
        detail = str(exc)
    elif isinstance(exc, PermissionError):
        status_code = status.HTTP_403_FORBIDDEN
        detail = str(exc)
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = (
            "document storage is temporarily unavailable"
            if isinstance(exc, ObjectStorageError)
            else str(exc)
        )
    return JSONResponse(status_code=status_code, content={"detail": detail})


for _error_type in (
    AdminNotFoundError,
    IdentityNotFoundError,
    DocumentNotFoundError,
    AdminConflictError,
    UploadConflictError,
    AdminValidationError,
    UploadValidationError,
    UploadTooLargeError,
    AuthorizationError,
    IdentityInactiveError,
    AuthServiceError,
    PermissionError,
    AdminExternalUnavailableError,
    ObjectStorageError,
    RuntimeError,
    ValueError,
):
    app.add_exception_handler(_error_type, _service_error)

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
app.include_router(knowledge_router, prefix=_PREFIX)
app.include_router(collections_router, prefix=_PREFIX)
app.include_router(documents_router, prefix=_PREFIX)
app.include_router(crons_router, prefix=_PREFIX)
app.include_router(bi_router, prefix=_PREFIX)
app.include_router(admin_router, prefix=_PREFIX)


def _get_health_service() -> HealthService:
    return HealthService(
        HealthSettings(
            qdrant_url=os.getenv("QDRANT_URL") or None,
            qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
            qdrant_collection=os.getenv("QDRANT_COLLECTION") or None,
            openai_base_url=(
                os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openrouter_base_url=(
                os.getenv("OPEN_ROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
            ),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
            chat_model=os.getenv("OPENAI_MODEL") or None,
            embedding_model=os.getenv("EMBEDDING_MODEL") or None,
            langfuse_base_url=(
                os.getenv("LANGFUSE_BASE_URL")
                or os.getenv("LANGFUSE_HOST")
                or "https://cloud.langfuse.com"
            ),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY") or None,
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY") or None,
        )
    )


@app.get(
    "/health",
    tags=["health"],
    response_model=HealthReport,
    response_model_exclude_none=True,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthReport}},
)
async def health(
    response: Response,
    health_service: HealthService = Depends(_get_health_service),
) -> HealthReport:
    report: HealthReport = await health_service.check()
    if report.status == "unhealthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


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
        host=os.getenv("BOTHESIS_HOST", "127.0.0.1"),
        port=int(os.getenv("BOTHESIS_PORT", "8000")),
        env_file=Path(__file__).with_name(".env"),
    )
