"""HTTP routers and the request/response models they exchange.

Every handler validates, delegates to a service, and returns. The models live
here so one import gives a router its whole transport contract; application
logic lives in ``bothesis.services``.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from bothesis.connector.protocol import BoundingBox, CitationInfo
from bothesis.services import KnowledgePreviewView


# --- Auth and RBAC ---


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


# --- Agent and chat ---


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


# --- Documents and search ---


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
    preview: KnowledgePreviewView | None = None


class DocumentUploadStartResponse(BaseModel):
    upload_required: bool
    target: DocumentUploadTarget | None = None
    document: DocumentMetadata


class CollectionDocumentUploadResponse(BaseModel):
    document: DocumentMetadata
    ingestion_status: Literal["ready", "failed"]
    created: bool

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=6, ge=1, le=20)
    collection_item_ids: list[UUID] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def validate_collection_ids(self) -> SearchRequest:
        if self.collection_item_ids is not None and len(
            self.collection_item_ids
        ) != len(set(self.collection_item_ids)):
            raise ValueError("Collection IDs must be unique")
        return self


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


# --- Citations and document viewer ---


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
    status: Literal["pending", "processing", "ready", "failed", "unsupported", "deleted"]
    external_url: str | None = None
    document_url: str | None = None
    preview: KnowledgePreviewView | None = None
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
    preview: KnowledgePreviewView | None = None
    citation: CitationInfo


# --- Scheduled jobs ---


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


# --- Business intelligence ---


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


# --- Tenant administration ---


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


class IntegrationConnectionCreate(AdminRequest):
    connector_key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = Field(default=None, repr=False)
    credential_type: str | None = Field(default=None, min_length=1, max_length=64)
    owner_type: Literal["user", "tenant"] = "tenant"


class IntegrationConnectionUpdate(AdminRequest):
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


class IngestionSourceCreate(AdminRequest):
    target_item_id: UUID
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)
    schedule: ScheduleInput | None = None


class IngestionSourceUpdate(AdminRequest):
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


__all__ = [
    "AccessRequestCreate",
    "AccessRequestDecision",
    "AdminRequest",
    "AdminRoleCreate",
    "AdminRoleUpdate",
    "BIQueryRequest",
    "BIQueryResponse",
    "ChatHistoryMessage",
    "ChatRequest",
    "CollectionAccessGrant",
    "CollectionCreate",
    "CollectionDocumentUploadResponse",
    "CollectionUpdate",
    "CronCreate",
    "CronJob",
    "CronRunResult",
    "CronUpdate",
    "DocumentDetail",
    "DocumentMetadata",
    "DocumentResult",
    "DocumentUploadStartRequest",
    "DocumentUploadStartResponse",
    "DocumentUploadTarget",
    "EffectivePermissions",
    "GroupCreate",
    "GroupMembersUpdate",
    "GroupUpdate",
    "IngestionSourceCreate",
    "IngestionSourceUpdate",
    "IntegrationConnectionCreate",
    "IntegrationConnectionUpdate",
    "ItemStatusUpdate",
    "KnowledgeCitationResponse",
    "KnowledgeItemViewer",
    "LoginRequest",
    "Message",
    "MessageSend",
    "MetricComputeRequest",
    "MetricDefinition",
    "MetricFilter",
    "MetricResult",
    "PermissionPatch",
    "RefreshRequest",
    "Role",
    "RoleCreate",
    "RoleUpdate",
    "ScheduleInput",
    "SearchRequest",
    "SearchResponse",
    "SpaceUpdate",
    "Thread",
    "ThreadCreate",
    "ThreadDetail",
    "TokenResponse",
    "UserCreate",
    "UserProfile",
    "UserUpdate",
    "ViewerElement",
    "ViewerFocus",
]
