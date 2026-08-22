"""BoThesis API — all route declarations. Implement services in bothesis/*/service.py."""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

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
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, EmailStr, Field, model_validator
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.engine import get_session

from bothesis.health import HealthReport, HealthService, HealthSettings
from bothesis.knowledge import CitationResolver
from bothesis.knowledge.protocol import BoundingBox, CitationInfo, CitationSpan, SourceIdentity, SourceProvider

if __name__ == "__main__":
    load_dotenv(Path(__file__).with_name(".env"), override=False)

_log = logging.getLogger(__name__)

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
    conversation_id: str | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=24)
    connector_mode: Literal["auto", "selected", "off"] = "auto"
    connector_ids: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_connector_selection(self) -> ChatRequest:
        if self.connector_mode == "selected" and not self.connector_ids:
            raise ValueError("selected connector mode requires at least one connector")
        if self.connector_mode != "selected" and self.connector_ids:
            raise ValueError("connector IDs are only accepted in selected mode")
        if len(self.connector_ids) != len(set(self.connector_ids)):
            raise ValueError("connector IDs must be unique")
        return self


class DocumentUploadStartRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=160)
    size_bytes: int = Field(ge=1)


class LegacyAttachmentUploadStart(DocumentUploadStartRequest):
    sha256: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    tenant_id: UUID
    user_id: UUID
    conversation_id: str | None = Field(default=None, min_length=1, max_length=256)


class LegacyAttachmentScope(BaseModel):
    tenant_id: UUID
    user_id: UUID
    conversation_id: str = Field(min_length=1, max_length=256)


class DocumentUploadTarget(BaseModel):
    mode: Literal["presigned", "api"]
    url: str
    method: str
    headers: dict[str, str]
    expires_at: str


class DocumentMetadata(BaseModel):
    id: str
    file_name: str
    content_type: str
    size_bytes: int
    upload_status: Literal["not_applicable", "pending", "available", "failed"]
    indexing_status: str
    created_at: str
    uploaded_at: str | None = None


class DocumentUploadStartResponse(BaseModel):
    upload_required: bool
    target: DocumentUploadTarget | None = None
    document: DocumentMetadata


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
attachments_router = APIRouter(prefix="/attachments", tags=["attachments"])

_agent: Any | None = None
_document_runtime: Any | None = None
_INSECURE_DEVELOPMENT_IDENTITY_ENV = "BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY"
_PHASE1_UNSCOPED_RETRIEVAL_ENV = "BOTHESIS_PHASE1_UNSCOPED_RETRIEVAL"


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


def _phase1_unscoped_retrieval_enabled() -> bool:
    """Allow the explicit single-tenant Phase 1 compatibility mode."""

    enabled = _environment_boolean(_PHASE1_UNSCOPED_RETRIEVAL_ENV)
    if enabled and not _environment_boolean(_INSECURE_DEVELOPMENT_IDENTITY_ENV):
        raise RuntimeError(
            f"{_PHASE1_UNSCOPED_RETRIEVAL_ENV} requires "
            f"{_INSECURE_DEVELOPMENT_IDENTITY_ENV}=true"
        )
    return enabled


class _LazyDocumentEmbedder:
    """Defer embedding configuration until Index On Demand is selected."""

    def __init__(self, *, base_url: str) -> None:
        self.model = os.getenv("EMBEDDING_MODEL", "").strip()
        self._base_url = base_url
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from bothesis.agent.transports.openrouter import OpenRouterTransport

            self._client = OpenRouterTransport(
                base_url=self._base_url,
                embedding_model=self.model or None,
            )
            self.model = self._client.embedding_model or ""
        return self._client

    async def embed_query(self, query: str) -> list[float]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        return (await self._embed([normalized_query]))[0]

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        normalized = [document.strip() for document in documents]
        if not normalized or any(not document for document in normalized):
            raise ValueError("documents must contain non-empty text")
        return await self._embed(normalized)

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        payload = await self._get_client().embeddings(
            input=inputs[0] if len(inputs) == 1 else inputs,
        )
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(inputs):
            raise ValueError("embedding response does not contain all vectors")
        indexed: list[tuple[int, list[float]]] = []
        for fallback_index, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError("embedding response vector is invalid")
            raw_vector = item.get("embedding")
            if not isinstance(raw_vector, list) or not raw_vector:
                raise ValueError("embedding response vector is invalid")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in raw_vector
            ):
                raise ValueError("embedding response vector is invalid")
            vector = [float(value) for value in raw_vector]
            if any(not math.isfinite(value) for value in vector):
                raise ValueError("embedding response vector is invalid")
            raw_index = item.get("index", fallback_index)
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise ValueError("embedding response index is invalid")
            indexed.append((raw_index, vector))
        indexed.sort(key=lambda item: item[0])
        if [index for index, _ in indexed] != list(range(len(inputs))):
            raise ValueError("embedding response indexes are invalid")
        return [vector for _, vector in indexed]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def _get_agent() -> Any:
    """Build the singleton agent without introducing a DI framework."""
    global _agent
    if _agent is None:
        from bothesis.agent import Agent, AgentConfig
        from bothesis.agent.tools import ToolRegistry
        from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
        from bothesis.agent.transports.openai import OpenAITransport
        from bothesis.agent.transports.openrouter import OpenRouterTransport
        from bothesis.document_index.vector_store import VectorStore
        from bothesis.knowledge.document_index import QdrantSemanticRetriever
        from bothesis.observability import create_langfuse_tracing

        registry = ToolRegistry()
        openrouter_base_url = os.getenv(
            "OPEN_ROUTER_BASE_URL",
            OpenRouterTransport.DEFAULT_BASE_URL,
        )
        allow_unscoped_retrieval = _phase1_unscoped_retrieval_enabled()
        if allow_unscoped_retrieval:
            logging.getLogger(__name__).warning(
                "Phase 1 unscoped admin retrieval is enabled; tenant filtering "
                "is disabled for admin chat requests"
            )
        retriever = QdrantSemanticRetriever(
            VectorStore(
                collection_name=os.getenv("QDRANT_COLLECTION"),
                url=os.getenv("QDRANT_URL"),
                api_key=os.getenv("QDRANT_API_KEY") or None,
                prefer_grpc=_environment_boolean("QDRANT_PREFER_GRPC"),
                timeout=8,
            ),
            _LazyDocumentEmbedder(base_url=openrouter_base_url),
            allow_unscoped_admin_retrieval=allow_unscoped_retrieval,
        )
        tracing = create_langfuse_tracing()
        registry.register(KnowledgeSearchTool(retriever, tracing=tracing))
        _agent = Agent(
            model=OpenRouterTransport(base_url=openrouter_base_url),
            tools=registry,
            config=AgentConfig(
                max_model_turns=int(os.getenv("BOTHESIS_MAX_MODEL_TURNS", "3")),
                max_tool_rounds=int(os.getenv("BOTHESIS_MAX_TOOL_ROUNDS", "2")),
                max_tool_calls=int(os.getenv("BOTHESIS_MAX_TOOL_CALLS", "6")),
                max_history_messages=int(
                    os.getenv("BOTHESIS_MAX_HISTORY_MESSAGES", "24")
                ),
                max_history_characters=int(
                    os.getenv("BOTHESIS_MAX_HISTORY_CHARACTERS", "24000")
                ),
                recent_history_messages=int(
                    os.getenv("BOTHESIS_RECENT_HISTORY_MESSAGES", "6")
                ),
                tool_timeout_seconds=float(
                    os.getenv("BOTHESIS_TOOL_TIMEOUT_SECONDS", "8")
                ),
            ),
            tracing=tracing,
        )
    return _agent


@dataclasses.dataclass(slots=True)
class _DocumentRuntime:
    uploads: Any
    conversations: Any
    session_factory: Any
    storage: Any
    _pipeline: Any | None = None

    @property
    def pipeline(self) -> Any:
        if self._pipeline is None:
            from bothesis.agent.transports.openrouter import OpenRouterTransport
            from bothesis.connector.document_pipeline import (
                DEFAULT_DIRECT_MAX_BYTES,
                DEFAULT_PROCESSING_MAX_BYTES,
                DocumentChunker,
                DocumentPipeline,
                FileParser,
            )
            from bothesis.connector.file.processing import FileProcessor
            from bothesis.connector.provider_cache import PostgresProviderFileCache
            from bothesis.document_index.vector_store import (
                QdrantDocumentIndex,
                VectorStore,
            )

            base_url = os.getenv(
                "OPEN_ROUTER_BASE_URL",
                OpenRouterTransport.DEFAULT_BASE_URL,
            )
            embedder = _LazyDocumentEmbedder(base_url=base_url)
            processing_max_bytes = int(
                os.getenv(
                    "BOTHESIS_DOCUMENT_MAX_PROCESSING_BYTES",
                    str(DEFAULT_PROCESSING_MAX_BYTES),
                )
            )
            self._pipeline = DocumentPipeline(
                self.session_factory,
                object_storage=self.storage,
                parser=FileParser(
                    FileProcessor(max_file_bytes=processing_max_bytes)
                ),
                chunker=DocumentChunker(
                    max_characters=int(
                        os.getenv("BOTHESIS_DOCUMENT_CHUNK_CHARACTERS", "4000")
                    ),
                    overlap_characters=int(
                        os.getenv("BOTHESIS_DOCUMENT_CHUNK_OVERLAP", "400")
                    ),
                ),
                embedder=embedder,
                vector_index=QdrantDocumentIndex(
                    VectorStore(
                        collection_name=os.getenv("QDRANT_COLLECTION"),
                        url=os.getenv("QDRANT_URL"),
                        api_key=os.getenv("QDRANT_API_KEY") or None,
                        prefer_grpc=_environment_boolean("QDRANT_PREFER_GRPC"),
                        timeout=20,
                    )
                ),
                provider_cache=PostgresProviderFileCache(self.session_factory),
                direct_max_bytes=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_DIRECT_MAX_BYTES",
                        str(DEFAULT_DIRECT_MAX_BYTES),
                    )
                ),
                processing_max_bytes=processing_max_bytes,
                retrieval_limit=int(
                    os.getenv("BOTHESIS_DOCUMENT_RETRIEVAL_LIMIT", "6")
                ),
                embedding_batch_size=int(
                    os.getenv("BOTHESIS_DOCUMENT_EMBEDDING_BATCH_SIZE", "32")
                ),
                download_url_seconds=int(
                    os.getenv("BOTHESIS_DOCUMENT_DOWNLOAD_URL_SECONDS", "300")
                ),
            )
        return self._pipeline

    async def aclose(self) -> None:
        if self._pipeline is not None:
            await self._pipeline.aclose()
        if self.storage is not None:
            await self.storage.aclose()


def _get_document_runtime() -> _DocumentRuntime:
    """Compose replaceable document services without a DI framework."""

    global _document_runtime
    if _document_runtime is None:
        from bothesis.db.engine import get_session_factory
        from bothesis.document_index.raw_storage import S3DocumentStorage
        from bothesis.services import (
            DEFAULT_MAX_DATABASE_BLOB_BYTES,
            DEFAULT_MAX_UPLOAD_BYTES,
            DEFAULT_UPLOAD_URL_SECONDS,
            ConversationService,
            UploadService,
        )

        session_factory = get_session_factory()
        storage_provider = (
            os.getenv("BOTHESIS_OBJECT_STORAGE_PROVIDER") or "aws_s3"
        ).strip().lower()
        if storage_provider == "aws_s3":
            bucket = (
                os.getenv("BOTHESIS_S3_BUCKET")
                or os.getenv("BOTHESIS_OBJECT_STORAGE_BUCKET")
                or ""
            ).strip()
            endpoint_url = (
                os.getenv("BOTHESIS_S3_ENDPOINT_URL")
                or os.getenv("BOTHESIS_OBJECT_STORAGE_ENDPOINT")
                or ""
            ).strip()
            if endpoint_url and not bucket:
                raise RuntimeError(
                    "BOTHESIS_S3_BUCKET is required when AWS S3 is configured"
                )
            storage = (
                S3DocumentStorage(
                    bucket=bucket,
                    region=(
                        os.getenv("BOTHESIS_S3_REGION")
                        or os.getenv("AWS_REGION")
                        or os.getenv("AWS_DEFAULT_REGION")
                        or None
                    ),
                    endpoint_url=endpoint_url or None,
                    addressing_style=(
                        os.getenv("BOTHESIS_S3_ADDRESSING_STYLE") or "auto"
                    ).strip(),
                    timeout_seconds=float(
                        os.getenv("BOTHESIS_S3_TIMEOUT_SECONDS", "20")
                    ),
                    max_pool_connections=int(
                        os.getenv("BOTHESIS_S3_MAX_POOL_CONNECTIONS", "20")
                    ),
                )
                if bucket
                else None
            )
        elif storage_provider == "cloudflare_r2":
            bucket = (
                os.getenv("BOTHESIS_R2_BUCKET")
                or os.getenv("BOTHESIS_OBJECT_STORAGE_BUCKET")
                or ""
            ).strip()
            account_id = (os.getenv("BOTHESIS_R2_ACCOUNT_ID") or "").strip()
            endpoint_url = (os.getenv("BOTHESIS_R2_ENDPOINT_URL") or "").strip()
            access_key_id = (os.getenv("BOTHESIS_R2_ACCESS_KEY_ID") or "").strip()
            secret_access_key = (
                os.getenv("BOTHESIS_R2_SECRET_ACCESS_KEY") or ""
            ).strip()
            if any((account_id, endpoint_url, access_key_id, secret_access_key)) and not bucket:
                raise RuntimeError(
                    "BOTHESIS_R2_BUCKET is required when Cloudflare R2 is configured"
                )
            if bucket and not (account_id or endpoint_url):
                raise RuntimeError(
                    "BOTHESIS_R2_ACCOUNT_ID or BOTHESIS_R2_ENDPOINT_URL is required"
                )
            if bucket and not (access_key_id and secret_access_key):
                raise RuntimeError(
                    "BOTHESIS_R2_ACCESS_KEY_ID and BOTHESIS_R2_SECRET_ACCESS_KEY are required"
                )
            storage = (
                S3DocumentStorage.for_cloudflare_r2(
                    bucket=bucket,
                    account_id=account_id or None,
                    endpoint_url=endpoint_url or None,
                    access_key_id=access_key_id or None,
                    secret_access_key=secret_access_key or None,
                    timeout_seconds=float(
                        os.getenv("BOTHESIS_R2_TIMEOUT_SECONDS", "20")
                    ),
                    max_pool_connections=int(
                        os.getenv("BOTHESIS_R2_MAX_POOL_CONNECTIONS", "20")
                    ),
                )
                if bucket
                else None
            )
        else:
            raise RuntimeError(
                "BOTHESIS_OBJECT_STORAGE_PROVIDER must be aws_s3 or cloudflare_r2"
            )
        _document_runtime = _DocumentRuntime(
            uploads=UploadService(
                session_factory,
                object_storage=storage,
                max_upload_bytes=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_MAX_UPLOAD_BYTES",
                        str(DEFAULT_MAX_UPLOAD_BYTES),
                    )
                ),
                max_database_blob_bytes=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_MAX_DATABASE_BLOB_BYTES",
                        str(DEFAULT_MAX_DATABASE_BLOB_BYTES),
                    )
                ),
                upload_url_seconds=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_UPLOAD_URL_SECONDS",
                        str(DEFAULT_UPLOAD_URL_SECONDS),
                    )
                ),
            ),
            conversations=ConversationService(session_factory),
            session_factory=session_factory,
            storage=storage,
        )
    return _document_runtime


def _document_metadata(document: Any) -> DocumentMetadata:
    return DocumentMetadata(
        id=str(document.id),
        file_name=str(document.metadata_.get("file_name") or document.title or "document"),
        content_type=document.mime_type or "application/octet-stream",
        size_bytes=document.size_bytes or 0,
        upload_status=document.upload_status,
        indexing_status=document.indexing_status,
        created_at=document.created_at.isoformat(),
        uploaded_at=(document.uploaded_at.isoformat() if document.uploaded_at else None),
    )


def _target_payload(target: Any | None) -> dict[str, Any] | None:
    if target is None:
        return None
    request = target.request
    return {
        "mode": target.mode,
        "url": request.url,
        "method": request.method,
        "headers": dict(request.headers),
        "expires_at": request.expires_at.isoformat(),
    }


def _legacy_document_metadata(document: DocumentMetadata) -> dict[str, Any]:
    direct = document.content_type in {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "application/pdf",
    }
    return {
        "id": document.id,
        "file_name": document.file_name,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "mode": "direct" if direct else "indexed",
        "status": document.upload_status,
        "created_at": document.created_at,
    }


def _document_http_error(exc: Exception) -> HTTPException:
    from bothesis.services import (
        AuthServiceError,
        AuthorizationError,
        DocumentNotFoundError,
    )
    from bothesis.document_index.raw_storage import ObjectStorageError
    from bothesis.services import (
        UploadConflictError,
        UploadTooLargeError,
        UploadValidationError,
    )

    if isinstance(exc, DocumentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, UploadTooLargeError):
        return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))
    if isinstance(exc, UploadConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, UploadValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )
    if isinstance(exc, AuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, AuthServiceError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(exc, ObjectStorageError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document storage is temporarily unavailable",
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="document service is not configured",
    )


async def _resolve_access(
    request: Request,
    session: AsyncSession,
    *,
    user_id: str | UUID | None = None,
    tenant_id: str | UUID | None = None,
) -> Any:
    from bothesis.services.request_identity import resolve_auth_context

    try:
        return await resolve_auth_context(
            request,
            session,
            claimed_user_id=user_id,
            claimed_tenant_id=tenant_id,
            allow_insecure_development_identity=bool(
                request.app.state.allow_insecure_development_identity
            ),
        )
    except Exception as exc:
        raise _document_http_error(exc) from exc


@attachments_router.post(
    "/uploads",
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def start_attachment_upload(
    body: LegacyAttachmentUploadStart,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Deprecated compatibility alias for the Document upload API."""
    try:
        access = await _resolve_access(
            request,
            session,
            user_id=body.user_id,
            tenant_id=body.tenant_id,
        )
        result = await _get_document_runtime().uploads.start_upload(
            access,
            idempotency_key=idempotency_key or body.sha256 or uuid4().hex,
            file_name=body.file_name,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc
    target = _target_payload(result.target)
    if target and target["mode"] == "api" and str(target["url"]).startswith("/"):
        target["url"] = (
            f"{str(request.base_url).rstrip('/')}{target['url']}"
            f"?tenant_id={body.tenant_id}&user_id={body.user_id}"
        )
    metadata = _document_metadata(result.document)
    return {
        "upload_id": str(result.document.id),
        "upload_required": result.upload_required,
        "upload": target,
        "attachment": _legacy_document_metadata(metadata),
    }


@attachments_router.post(
    "/uploads/{upload_id}/complete",
    deprecated=True,
)
async def complete_attachment_upload(
    upload_id: UUID,
    body: LegacyAttachmentScope,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        access = await _resolve_access(
            request,
            session,
            user_id=body.user_id,
            tenant_id=body.tenant_id,
        )
        document = await _get_document_runtime().uploads.complete_upload(
            access,
            upload_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc
    return _legacy_document_metadata(_document_metadata(document))


@attachments_router.delete(
    "/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    deprecated=True,
)
async def release_attachment(
    attachment_id: UUID,
    request: Request,
    tenant_id: str = Query(min_length=1, max_length=256),
    user_id: str = Query(min_length=1, max_length=256),
    conversation_id: str | None = Query(default=None, min_length=1, max_length=256),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        access = await _resolve_access(
            request,
            session,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        await _get_document_runtime().pipeline.soft_delete_document(
            attachment_id,
            access=access,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc


@agent_router.post("/chat")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    """Return the agent event stream as server-sent events."""
    from bothesis.agent.models import AgentContext, ConversationMessage
    from bothesis.db.engine import get_session_factory

    request_id = uuid4().hex
    conversation_id = _conversation_id(body.conversation_id)
    try:
        async with get_session_factory()() as auth_session:
            access = await _resolve_access(
                request,
                auth_session,
                user_id=body.user_id,
                tenant_id=body.tenant_id,
            )
            from bothesis.services import (
                KNOWLEDGE_READ_PERMISSION,
                require_tenant_permission,
            )

            require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
            selected_connector_ids: tuple[int, ...] | None = None
            allowed_tool_names: tuple[str, ...] | None = (
                () if body.connector_mode == "off" else None
            )
            if body.connector_mode == "selected":
                from bothesis.services import DatasourceService

                authorized = await DatasourceService(
                    auth_session
                ).list_chat_connectors(
                    access,
                    connector_ids=body.connector_ids,
                )
                selected_connector_ids = tuple(
                    int(item["id"]) for item in authorized["items"]
                )
                allowed_tool_names = tuple(
                    sorted(
                        {
                            capability
                            for item in authorized["items"]
                            for capability in item["capabilities"]
                        }
                    )
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc
    if access.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="an active tenant membership is required for chat",
        )
    context = AgentContext(
        user_id=str(access.user_id),
        tenant_id=str(access.tenant_id),
        roles=[access.role_code] if access.role_code else [],
        reader_ids=tuple(
            sorted(
                {
                    f"email:{access.email.strip().lower()}",
                    *(
                        token.strip().lower()
                        for token in access.principal_tokens
                        if token.strip()
                    ),
                }
            )
        ),
        is_admin=access.is_admin,
        conversation_id=str(conversation_id),
        request_id=request_id,
        history=tuple(
            ConversationMessage(role=message.role, content=message.content)
            for message in body.history
        ),
        connector_ids=selected_connector_ids,
        allowed_tool_names=allowed_tool_names,
    )
    try:
        agent = _get_agent()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent service is not configured",
        ) from exc

    async def event_gen():
        stream = agent.run(body.message, context)
        try:
            async for event in stream:
                if await request.is_disconnected():
                    break
                yield f"data: {event.model_dump_json()}\n\n"
        finally:
            await stream.aclose()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@agent_router.get("/connectors")
async def list_chat_connectors(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List active tenant connections available to the chat picker."""

    from bothesis.services import DatasourceService

    access = await _resolve_access(request, session)
    return await DatasourceService(session).list_chat_connectors(access)


def _conversation_id(value: str | None) -> UUID:
    if value is None:
        return uuid4()
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="conversation_id must be a UUID",
        ) from exc


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
# Connectors router
# ---------------------------------------------------------------------------

connectors_router = APIRouter(prefix="/connectors", tags=["connectors"])


@connectors_router.get("", response_model=list[Connector])
async def list_connectors(
    current_user: UserProfile = Depends(get_current_user),
) -> list[Connector]:
    # return await connectors_service.list(current_user.tenant_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.post(
    "", response_model=Connector, status_code=status.HTTP_201_CREATED
)
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
    connector_id: UUID,
    body: ConnectorUpdate,
    current_user: UserProfile = Depends(get_current_user),
) -> Connector:
    # return await connectors_service.update(current_user.tenant_id, connector_id, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: UUID, current_user: UserProfile = Depends(get_current_user)
) -> None:
    # await connectors_service.delete(current_user.tenant_id, connector_id)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@connectors_router.post(
    "/{connector_id}/sync",
    response_model=SyncStatus,
    status_code=status.HTTP_202_ACCEPTED,
)
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

knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@knowledge_router.get(
    "/items/{item_id:path}/citations/{chunk_id:path}",
    response_model=KnowledgeCitationResponse,
)
async def get_knowledge_citation(
    item_id: str,
    chunk_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> KnowledgeCitationResponse:
    """Resolve a citation and any raw-document URL only when it is opened."""

    try:
        access = await _resolve_access(request, session)
        from bothesis.services import DocumentNotFoundError, DocumentService

        document, record = await DocumentService(session).get_document_and_chunk_by_item_id(
            item_id,
            chunk_id,
            access=access,
        )
    except DocumentNotFoundError:
        return await _qdrant_citation(item_id, chunk_id, access)
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc

    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="citation not found")
    citation = _record_citation(record)
    source = _file_source(document)
    return KnowledgeCitationResponse(
        item_id=item_id,
        chunk_id=chunk_id,
        title=document.title or str(document.id),
        content_type=document.mime_type or "text/plain",
        document_url=_presigned_document_url(document),
        external_url=CitationResolver.original_url(source, citation),
        citation=citation,
    )


@knowledge_router.get(
    "/items/{item_id:path}",
    response_model=KnowledgeItemViewer,
)
async def get_knowledge_item_viewer(
    item_id: str,
    request: Request,
    chunk: str | None = Query(default=None, min_length=1, max_length=512),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeItemViewer:
    """Return a permission-checked normalized document for citation navigation."""

    try:
        access = await _resolve_access(request, session)
        from bothesis.services import DocumentNotFoundError, DocumentService

        document_service = DocumentService(session)
        if chunk:
            document, targeted_chunk = await document_service.get_document_and_chunk_by_item_id(
                item_id,
                chunk,
                access=access,
            )
        else:
            document = await document_service.get_document_by_item_id(
                item_id,
                access=access,
            )
            targeted_chunk = None
    except DocumentNotFoundError:
        return await _qdrant_item_viewer(item_id, chunk, access)
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc

    if targeted_chunk is not None:
        viewer_records = [targeted_chunk]
    elif chunk is None:
        viewer_records = await document_service.get_chunks(
            document.id,
            access=access,
            limit=100,
        )
    else:
        viewer_records = []
    elements, chunks_by_id = _viewer_elements(document, records=viewer_records)
    focus = None
    if chunk:
        record = chunks_by_id.get(chunk)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="citation not found")
        focus = ViewerFocus(
            chunk_id=chunk,
            chunk_text=record.content,
            citation=_record_citation(record),
        )
    return KnowledgeItemViewer(
        item_id=item_id,
        title=document.title or str(document.id),
        content_type=document.mime_type or "text/plain",
        external_url=CitationResolver.original_url(
            _file_source(document),
            _record_citation(chunks_by_id[chunk]) if chunk in chunks_by_id else CitationInfo(),
        ),
        document_url=_presigned_document_url(document) if chunk else None,
        elements=elements,
        focus=focus,
    )


def _viewer_elements(
    document: Any,
    *,
    records: list[Any] | None = None,
) -> tuple[list[ViewerElement], dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    chunks_by_id: dict[str, Any] = {}
    item_id = str(document.id)
    source_records = document.chunks if records is None else records
    for record in sorted(source_records, key=lambda value: value.chunk_index):
        chunk_id = f"{item_id}:{record.chunk_index}"
        chunks_by_id[chunk_id] = record
        chunks_by_id[f"{record.id}"] = record
        citation = _record_citation(record)
        _add_citation_content(groups, record.content, citation)

    elements = [
        ViewerElement(
            element_id=element_id,
            text="".join(value["chars"]).rstrip(),
            page=value["page"],
            section=value["section"],
            section_path=value["section_path"],
            anchor=value["anchor"],
            bounding_box=value["bounding_box"],
        )
        for element_id, value in groups.items()
        if "".join(value["chars"]).strip()
    ]
    return elements, chunks_by_id


def _viewer_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _viewer_int(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _viewer_bbox(value: object) -> BoundingBox | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return BoundingBox.model_validate(value)
    except ValueError:
        return None


async def _qdrant_item_viewer(
    item_id: str,
    chunk_id: str | None,
    access: Any,
) -> KnowledgeItemViewer:
    """Resolve connector-backed items from the permission-filtered index.

    Connector items are not required to be upload Documents in PostgreSQL, but
    their normalized chunks still contain enough structure for an internal
    evidence viewer. The same tenant/ACL/tombstone filter is applied before any
    payload is exposed.
    """

    if access.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    try:
        payloads = await _qdrant_payloads(item_id, access, chunk_id=chunk_id)
        if not payloads:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
        return _viewer_from_payloads(item_id, chunk_id, payloads)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        ) from exc


def _viewer_from_payloads(
    item_id: str,
    chunk_id: str | None,
    payloads: list[dict[str, Any]],
) -> KnowledgeItemViewer:
    ordered = sorted(payloads, key=lambda payload: _viewer_payload_int(payload, "chunk_index") or 0)
    groups: dict[str, dict[str, Any]] = {}
    by_chunk: dict[str, dict[str, Any]] = {}
    for payload in ordered:
        index = _viewer_payload_int(payload, "chunk_index") or 0
        current_chunk_id = _viewer_payload_text(payload, "chunk_id") or f"{item_id}:{index}"
        by_chunk[current_chunk_id] = payload
        by_chunk[f"{item_id}:{index}"] = payload
        citation = _payload_citation(payload)
        _add_citation_content(
            groups,
            _viewer_payload_text(payload, "chunk_text") or "",
            citation,
        )

    elements = [
        ViewerElement(
            element_id=element_id,
            text="".join(value["chars"]).rstrip(),
            page=value["page"],
            section=value["section"],
            section_path=value["section_path"],
            anchor=value["anchor"],
            bounding_box=value["bounding_box"],
        )
        for element_id, value in groups.items()
        if "".join(value["chars"]).strip()
    ]
    focus_payload = by_chunk.get(chunk_id or "") if chunk_id else None
    focus = _viewer_focus_from_payload(chunk_id, focus_payload)
    first = ordered[0]
    first_citation = _payload_citation(first)
    first_source = _payload_source(first, item_id)
    return KnowledgeItemViewer(
        item_id=item_id,
        title=_viewer_payload_text(first, "title") or item_id,
        content_type=_viewer_payload_text(first, "content_type") or "text/plain",
        external_url=CitationResolver.original_url(first_source, first_citation),
        document_url=None,
        elements=elements,
        focus=focus,
    )


def _viewer_focus_from_payload(
    chunk_id: str | None,
    payload: dict[str, Any] | None,
) -> ViewerFocus | None:
    if not chunk_id or payload is None:
        return None
    return ViewerFocus(
        chunk_id=chunk_id,
        chunk_text=_viewer_payload_text(payload, "chunk_text") or "",
        citation=_payload_citation(payload),
    )


def _viewer_payload_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _viewer_payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _viewer_payload_strings(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _record_citation(record: Any) -> CitationInfo:
    metadata = dict(record.metadata_)
    spans = _citation_spans(metadata.get("citation_spans"))
    if not spans:
        element_id = _viewer_text(metadata, "element_id") or (
            f"element_{record.chunk_index + 1:03d}"
        )
        start = _viewer_int(metadata, "start_offset")
        end = _viewer_int(metadata, "end_offset")
        spans = [
            CitationSpan(
                page=record.start_page_number or record.end_page_number,
                element_id=element_id,
                start_offset=start if start is not None else 0,
                end_offset=end if end is not None else len(record.content),
                bounding_box=_viewer_bbox(metadata.get("bounding_box")),
            )
        ]
    section_path = tuple(record.heading_path or ())
    return CitationInfo(
        section=section_path[-1] if section_path else None,
        section_path=section_path,
        anchor=_viewer_text(metadata, "anchor"),
        spans=tuple(spans),
    )


def _payload_citation(payload: Mapping[str, Any]) -> CitationInfo:
    return CitationInfo(
        section=_viewer_payload_text(dict(payload), "citation_section"),
        section_path=tuple(_viewer_payload_strings(dict(payload), "citation_section_path")),
        anchor=_viewer_payload_text(dict(payload), "citation_anchor"),
        spans=tuple(_citation_spans(payload.get("citation_spans"))),
    )


def _citation_spans(value: object) -> list[CitationSpan]:
    if not isinstance(value, (list, tuple)):
        return []
    output: list[CitationSpan] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        try:
            output.append(
                CitationSpan(
                    page=_viewer_payload_int(dict(raw), "page"),
                    element_id=_viewer_payload_text(dict(raw), "element_id"),
                    start_offset=_viewer_payload_int(dict(raw), "start_offset"),
                    end_offset=_viewer_payload_int(dict(raw), "end_offset"),
                    bounding_box=_viewer_bbox(raw.get("bounding_box")),
                )
            )
        except ValueError:
            continue
    return output


def _add_citation_content(
    groups: dict[str, dict[str, Any]],
    content: str,
    citation: CitationInfo,
) -> None:
    cursor = 0
    for index, span in enumerate(citation.spans):
        element_id = span.element_id or f"element_{index + 1:03d}"
        if span.start_offset is None or span.end_offset is None:
            segment = content[cursor:]
            start = 0
        else:
            length = max(0, span.end_offset - span.start_offset)
            segment = content[cursor:cursor + length]
            start = span.start_offset
            cursor += length
        if index + 1 < len(citation.spans) and content[cursor:cursor + 2] == "\n\n":
            cursor += 2
        group = groups.setdefault(
            element_id,
            {
                "chars": [],
                "page": span.page,
                "section": citation.section,
                "section_path": list(citation.section_path),
                "anchor": citation.anchor,
                "bounding_box": span.bounding_box,
            },
        )
        chars: list[str] = group["chars"]
        end = start + len(segment)
        if len(chars) < end:
            chars.extend(" " for _ in range(end - len(chars)))
        for offset, character in enumerate(segment, start=start):
            chars[offset] = character


def _find_document_chunk(document: Any, chunk_id: str) -> Any | None:
    for record in document.chunks:
        if chunk_id in {str(record.id), f"{document.id}:{record.chunk_index}"}:
            return record
    return None


def _file_source(document: Any) -> SourceIdentity:
    return SourceIdentity(
        connector_id="upload",
        provider=SourceProvider.FILE,
        external_id=str(document.id),
        url=document.source_url,
    )


def _presigned_document_url(document: Any) -> str | None:
    raw_storage_key = getattr(document, "raw_storage_key", None)
    if not raw_storage_key:
        return None
    try:
        runtime = _get_document_runtime()
        if runtime.storage is None:
            return None
        request = runtime.storage.presign_download(
            raw_storage_key,
            expires_seconds=max(
                1,
                min(
                    600,
                    int(os.getenv("BOTHESIS_DOCUMENT_CITATION_URL_SECONDS", "300")),
                ),
            ),
        )
        return request.url
    except Exception:
        log.exception("could not generate citation document URL")
        return None


async def _qdrant_payloads(
    item_id: str,
    access: Any,
    *,
    chunk_id: str | None = None,
) -> list[dict[str, Any]]:
    from qdrant_client import models as qmodels
    from bothesis.document_index.vector_store import VectorStore

    reader_ids = {
        "public",
        str(access.user_id).strip().lower(),
        f"email:{access.email.strip().lower()}",
        *(token.strip().lower() for token in access.principal_tokens if token.strip()),
    }
    store = VectorStore(
        collection_name=os.getenv("QDRANT_COLLECTION"),
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY") or None,
        prefer_grpc=_environment_boolean("QDRANT_PREFER_GRPC"),
        timeout=8,
    )
    access_conditions = store.access_conditions(
        tenant_id=str(access.tenant_id),
        reader_ids=reader_ids,
        is_admin=access.is_admin,
    )
    conditions = [
        *access_conditions,
        qmodels.FieldCondition(
            key="item_id",
            match=qmodels.MatchValue(value=item_id),
        ),
    ]
    if chunk_id:
        conditions.append(
            qmodels.FieldCondition(
                key="chunk_id",
                match=qmodels.MatchValue(value=chunk_id),
            )
        )
    points, _ = await store.scroll_points(
        scroll_filter=qmodels.Filter(must=conditions),
        # A targeted citation only needs its own chunk.  The un-targeted
        # landing view is deliberately bounded; large documents are opened
        # through citation links rather than materializing the whole index.
        limit=1 if chunk_id else 100,
        with_payload=True,
        with_vectors=False,
    )
    return [
        dict(point.payload)
        for point in points
        if isinstance(getattr(point, "payload", None), dict)
    ]


async def _qdrant_citation(
    item_id: str,
    chunk_id: str,
    access: Any,
) -> KnowledgeCitationResponse:
    if access.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="citation not found")
    try:
        payloads = await _qdrant_payloads(item_id, access, chunk_id=chunk_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="citation not found") from exc
    if not payloads:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="citation not found")
    payload = payloads[0]
    citation = _payload_citation(payload)
    source = _payload_source(payload, item_id)
    return KnowledgeCitationResponse(
        item_id=item_id,
        chunk_id=chunk_id,
        title=_viewer_payload_text(payload, "title") or item_id,
        content_type=_viewer_payload_text(payload, "content_type") or "text/plain",
        document_url=None,
        external_url=CitationResolver.original_url(source, citation),
        citation=citation,
    )


def _payload_source(payload: Mapping[str, Any], item_id: str) -> SourceIdentity:
    provider_value = str(payload.get("provider") or SourceProvider.FILE.value)
    try:
        provider = SourceProvider(provider_value)
    except ValueError:
        provider = SourceProvider.FILE
    return SourceIdentity(
        connector_id=str(payload.get("connector_id") or "unknown"),
        provider=provider,
        external_id=str(payload.get("external_id") or item_id),
        url=_viewer_payload_text(dict(payload), "source_url"),
    )


documents_router = APIRouter(prefix="/documents", tags=["documents"])


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
    session: AsyncSession = Depends(get_session),
) -> DocumentUploadStartResponse:
    """Commit uploader-private metadata before returning any binary target."""

    try:
        access = await _resolve_access(request, session)
        result = await _get_document_runtime().uploads.start_upload(
            access,
            idempotency_key=idempotency_key,
            file_name=body.file_name,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc
    return DocumentUploadStartResponse(
        upload_required=result.upload_required,
        target=(
            DocumentUploadTarget.model_validate(_target_payload(result.target))
            if result.target is not None
            else None
        ),
        document=_document_metadata(result.document),
    )


@documents_router.put(
    "/{document_id}/content",
    response_model=DocumentMetadata,
)
async def store_document_content(
    document_id: UUID,
    request: Request,
    tenant_id: str | None = Query(default=None, min_length=1, max_length=256),
    user_id: str | None = Query(default=None, min_length=1, max_length=256),
    session: AsyncSession = Depends(get_session),
) -> DocumentMetadata:
    """Bounded PostgreSQL fallback; normal large uploads use presigned PUT."""

    try:
        access = await _resolve_access(
            request,
            session,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        uploads = _get_document_runtime().uploads
        document = await uploads.get_document(access, document_id)
        request_type = request.headers.get("content-type", "").split(";", 1)[0].casefold()
        if request_type and request_type != (document.mime_type or "").casefold():
            from bothesis.services import UploadValidationError

            raise UploadValidationError("uploaded content type does not match document metadata")
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > uploads.max_database_blob_bytes:
                from bothesis.services import UploadTooLargeError

                raise UploadTooLargeError(
                    "API upload exceeds the PostgreSQL fallback limit"
                )
            content.extend(chunk)
        stored = await uploads.store_fallback_content(
            access,
            document_id,
            bytes(content),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc
    return _document_metadata(stored)


@documents_router.post(
    "/{document_id}/complete",
    response_model=DocumentMetadata,
)
async def complete_document_upload(
    document_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DocumentMetadata:
    try:
        access = await _resolve_access(request, session)
        document = await _get_document_runtime().uploads.complete_upload(
            access,
            document_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc
    return _document_metadata(document)


@documents_router.post("/search", response_model=SearchResponse)
async def search_documents(
    body: SearchRequest, current_user: UserProfile = Depends(get_current_user)
) -> SearchResponse:
    """Permission-filtered semantic search across all indexed sources."""
    # return await document_index_service.search(current_user, body)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@documents_router.post(
    "/ingest", response_model=DocumentDetail, status_code=status.HTTP_202_ACCEPTED
)
async def ingest_document(
    file: UploadFile = File(...), current_user: UserProfile = Depends(get_current_user)
) -> DocumentDetail:
    """Upload and index a file (PDF, DOCX, TXT, …)."""
    # return await document_index_service.ingest(current_user, file)
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


@documents_router.get("/{doc_id}", response_model=DocumentMetadata)
async def get_document(
    doc_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DocumentMetadata:
    try:
        access = await _resolve_access(request, session)
        document = await _get_document_runtime().uploads.get_document(access, doc_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc
    return _document_metadata(document)


@documents_router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        access = await _resolve_access(request, session)
        await _get_document_runtime().pipeline.soft_delete_document(
            doc_id,
            access=access,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _document_http_error(exc) from exc


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
# App assembly
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    try:
        yield
    finally:
        if _document_runtime is not None:
            await _document_runtime.aclose()


app = FastAPI(
    title="BoThesis API",
    version="0.1.0",
    description="Enterprise knowledge and BI assistant.",
    lifespan=_app_lifespan,
)
app.state.allow_insecure_development_identity = _environment_boolean(
    _INSECURE_DEVELOPMENT_IDENTITY_ENV
)

from bothesis.api import register_admin_error_handlers
from bothesis.api.admin import admin_router

register_admin_error_handlers(app)

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
app.include_router(attachments_router, prefix=_PREFIX)
app.include_router(connectors_router, prefix=_PREFIX)
app.include_router(knowledge_router, prefix=_PREFIX)
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
        host="127.0.0.1",
        port=int(os.getenv("BOTHESIS_PORT", "8000")),
        env_file=Path(__file__).with_name(".env"),
    )
