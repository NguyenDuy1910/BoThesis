"""Public contracts and primary database-backed services for Enterprise Agent.

Service modules contain only their primary service class. Contexts, DTOs,
errors, and shared constants live here so callers use one stable boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bothesis.integrations import PendingAuthorization

from bothesis.connector.protocol import Chunk, DocumentItem
from bothesis.db.models import Item, ItemUpload
from bothesis.storage import PresignedRequest

ACTIVE_STATUS = "active"
INACTIVE_STATUS = "inactive"

#: Connection lifecycle. These describe the *grant*, never a sync run.
CONNECTION_DRAFT = "draft"
CONNECTION_CONNECTED = "connected"
CONNECTION_EXPIRED = "expired"
CONNECTION_REAUTH_REQUIRED = "reauth_required"
CONNECTION_REVOKED = "revoked"
CONNECTION_ERROR = "error"
CONNECTION_DISCONNECTED = "disconnected"
CONNECTION_STATUSES = (
    CONNECTION_DRAFT,
    CONNECTION_CONNECTED,
    CONNECTION_EXPIRED,
    CONNECTION_REAUTH_REQUIRED,
    CONNECTION_REVOKED,
    CONNECTION_ERROR,
    CONNECTION_DISCONNECTED,
)
#: A connection in any of these states cannot reach the provider until someone
#: authorizes it again.
CONNECTION_NEEDS_AUTHORIZATION = (
    CONNECTION_EXPIRED,
    CONNECTION_REAUTH_REQUIRED,
    CONNECTION_REVOKED,
    CONNECTION_DISCONNECTED,
)

#: Ingestion Source enablement and health. Run state lives in the workflow.
SOURCE_READY = "ready"
SOURCE_PAUSED = "paused"
SOURCE_FAILED = "failed"
SOURCE_CONNECTION_REQUIRED = "connection_required"
SOURCE_DISABLED = "disabled"
SOURCE_STATUSES = (
    SOURCE_READY,
    SOURCE_PAUSED,
    SOURCE_FAILED,
    SOURCE_CONNECTION_REQUIRED,
    SOURCE_DISABLED,
)
#: A source the worker may run, and write Items for. A failed source is included
#: because retrying one is exactly how it stops being failed.
RUNNABLE_SOURCE_STATUSES = (SOURCE_READY, SOURCE_FAILED)

#: Who a Connection acts as. A workspace connection is shared enterprise
#: access; a personal connection acts as one member and is never shared.
OWNER_TENANT = "tenant"
OWNER_USER = "user"
OWNER_TYPES = (OWNER_TENANT, OWNER_USER)
MESSAGE_ITEM_RELATIONS = frozenset({"attachment", "reference", "output"})

#: The three scopes authorization is ever granted at. They mirror the domain
#: exactly: the platform owns Tenants, a Tenant owns Collections, and a
#: Collection owns the Documents beneath it.
PLATFORM_SCOPE = "platform"
TENANT_SCOPE = "tenant"
COLLECTION_SCOPE = "collection"
ROLE_SCOPES = (PLATFORM_SCOPE, TENANT_SCOPE, COLLECTION_SCOPE)

#: Platform capabilities. They are deliberately enumerated instead of collapsed
#: into one "root" flag so a future support or security role can hold a subset.
PLATFORM_TENANT_READ_PERMISSION = "platform.tenant.read"
PLATFORM_USER_READ_PERMISSION = "platform.user.read"
PLATFORM_AUDIT_READ_PERMISSION = "platform.audit.read"
PLATFORM_HEALTH_READ_PERMISSION = "platform.health.read"

#: Tenant administration capabilities.
TENANT_READ_PERMISSION = "tenant.read"
TENANT_MANAGE_PERMISSION = "tenant.manage"
USER_MANAGE_PERMISSION = "user.manage"
ROLE_MANAGE_PERMISSION = "role.manage"
GROUP_MANAGE_PERMISSION = "group.manage"
SOURCE_MANAGE_PERMISSION = "source.manage"
ACCESS_MANAGE_PERMISSION = "access.manage"
AUDIT_READ_PERMISSION = "audit.read"
ITEM_MANAGE_PERMISSION = "item.manage"
KNOWLEDGE_READ_PERMISSION = "knowledge.read"

#: Collection capabilities. Documents are governed by the Collection that
#: contains them, so they need no permissions of their own.
COLLECTION_READ_PERMISSION = "collection.read"
COLLECTION_UPDATE_PERMISSION = "collection.update"
COLLECTION_DELETE_PERMISSION = "collection.delete"
COLLECTION_SHARE_PERMISSION = "collection.share"


@dataclass(frozen=True, slots=True)
class PermissionDefinition:
    """One product action, and the role scopes allowed to carry it."""

    code: str
    description: str
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    """A system role: a named permission bundle owned by the platform."""

    code: str
    display_name: str
    scope_type: str
    permission_codes: tuple[str, ...]


_PLATFORM_ONLY = frozenset({PLATFORM_SCOPE})
_TENANT_ONLY = frozenset({TENANT_SCOPE})
#: A Collection capability granted at tenant scope applies to every Collection
#: in that tenant. That is what makes a tenant administrator able to read the
#: whole workspace without a per-Collection grant, and without a special case.
_TENANT_OR_COLLECTION = frozenset({TENANT_SCOPE, COLLECTION_SCOPE})

PERMISSION_CATALOG: tuple[PermissionDefinition, ...] = (
    PermissionDefinition(
        PLATFORM_TENANT_READ_PERMISSION,
        "Read the workspace inventory and platform overview",
        _PLATFORM_ONLY,
    ),
    PermissionDefinition(
        PLATFORM_USER_READ_PERMISSION,
        "Read user identities across workspaces",
        _PLATFORM_ONLY,
    ),
    PermissionDefinition(
        PLATFORM_AUDIT_READ_PERMISSION,
        "Read audit events across workspaces",
        _PLATFORM_ONLY,
    ),
    PermissionDefinition(
        PLATFORM_HEALTH_READ_PERMISSION,
        "Read platform service health",
        _PLATFORM_ONLY,
    ),
    PermissionDefinition(
        ACCESS_MANAGE_PERMISSION,
        "Review access requests and manage Collection access",
        _TENANT_ONLY,
    ),
    PermissionDefinition(
        AUDIT_READ_PERMISSION, "Read tenant administration audit events", _TENANT_ONLY
    ),
    PermissionDefinition(
        GROUP_MANAGE_PERMISSION, "Manage groups and group membership", _TENANT_ONLY
    ),
    PermissionDefinition(
        ITEM_MANAGE_PERMISSION,
        "Manage canonical Item lifecycle and indexing",
        _TENANT_ONLY,
    ),
    PermissionDefinition(
        KNOWLEDGE_READ_PERMISSION,
        "Read tenant knowledge through permission filters",
        _TENANT_ONLY,
    ),
    PermissionDefinition(
        ROLE_MANAGE_PERMISSION, "Manage roles and role assignments", _TENANT_ONLY
    ),
    PermissionDefinition(
        SOURCE_MANAGE_PERMISSION,
        "Manage data sources, scopes, and ingestion",
        _TENANT_ONLY,
    ),
    PermissionDefinition(
        TENANT_READ_PERMISSION,
        "Read the tenant profile and administration overview",
        _TENANT_ONLY,
    ),
    PermissionDefinition(
        TENANT_MANAGE_PERMISSION, "Manage tenant profile and settings", _TENANT_ONLY
    ),
    PermissionDefinition(
        USER_MANAGE_PERMISSION, "Manage users and tenant membership", _TENANT_ONLY
    ),
    PermissionDefinition(
        COLLECTION_READ_PERMISSION,
        "Read a Collection and the Documents it contains",
        _TENANT_OR_COLLECTION,
    ),
    PermissionDefinition(
        COLLECTION_UPDATE_PERMISSION,
        "Add, update, and remove content in a Collection",
        _TENANT_OR_COLLECTION,
    ),
    PermissionDefinition(
        COLLECTION_DELETE_PERMISSION, "Delete a Collection", _TENANT_OR_COLLECTION
    ),
    PermissionDefinition(
        COLLECTION_SHARE_PERMISSION,
        "Grant and revoke access to a Collection",
        _TENANT_OR_COLLECTION,
    ),
)

PERMISSIONS_BY_CODE: dict[str, PermissionDefinition] = {
    permission.code: permission for permission in PERMISSION_CATALOG
}

PLATFORM_ADMIN_ROLE = "platform_admin"
TENANT_ADMIN_ROLE = "tenant_admin"
TENANT_MEMBER_ROLE = "tenant_member"
COLLECTION_OWNER_ROLE = "collection_owner"
COLLECTION_EDITOR_ROLE = "collection_editor"
COLLECTION_VIEWER_ROLE = "collection_viewer"

#: Roles the platform defines and keeps in step with the catalog above. A
#: tenant may define its own roles, but never one of these codes.
SYSTEM_ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        PLATFORM_ADMIN_ROLE,
        "Platform Administrator",
        PLATFORM_SCOPE,
        (
            PLATFORM_AUDIT_READ_PERMISSION,
            PLATFORM_HEALTH_READ_PERMISSION,
            PLATFORM_TENANT_READ_PERMISSION,
            PLATFORM_USER_READ_PERMISSION,
        ),
    ),
    RoleDefinition(
        TENANT_ADMIN_ROLE,
        "Workspace Administrator",
        TENANT_SCOPE,
        (
            ACCESS_MANAGE_PERMISSION,
            AUDIT_READ_PERMISSION,
            COLLECTION_DELETE_PERMISSION,
            COLLECTION_READ_PERMISSION,
            COLLECTION_SHARE_PERMISSION,
            COLLECTION_UPDATE_PERMISSION,
            GROUP_MANAGE_PERMISSION,
            ITEM_MANAGE_PERMISSION,
            KNOWLEDGE_READ_PERMISSION,
            ROLE_MANAGE_PERMISSION,
            SOURCE_MANAGE_PERMISSION,
            TENANT_MANAGE_PERMISSION,
            TENANT_READ_PERMISSION,
            USER_MANAGE_PERMISSION,
        ),
    ),
    RoleDefinition(
        TENANT_MEMBER_ROLE,
        "Workspace Member",
        TENANT_SCOPE,
        (KNOWLEDGE_READ_PERMISSION, TENANT_READ_PERMISSION),
    ),
    RoleDefinition(
        COLLECTION_OWNER_ROLE,
        "Collection Owner",
        COLLECTION_SCOPE,
        (
            COLLECTION_DELETE_PERMISSION,
            COLLECTION_READ_PERMISSION,
            COLLECTION_SHARE_PERMISSION,
            COLLECTION_UPDATE_PERMISSION,
        ),
    ),
    RoleDefinition(
        COLLECTION_EDITOR_ROLE,
        "Collection Editor",
        COLLECTION_SCOPE,
        (COLLECTION_READ_PERMISSION, COLLECTION_UPDATE_PERMISSION),
    ),
    RoleDefinition(
        COLLECTION_VIEWER_ROLE,
        "Collection Viewer",
        COLLECTION_SCOPE,
        (COLLECTION_READ_PERMISSION,),
    ),
)

SYSTEM_ROLES_BY_CODE: dict[str, RoleDefinition] = {
    role.code: role for role in SYSTEM_ROLES
}
#: The Collection roles a share grant or an access request may ask for,
#: strongest first.
COLLECTION_ROLE_CODES = (
    COLLECTION_OWNER_ROLE,
    COLLECTION_EDITOR_ROLE,
    COLLECTION_VIEWER_ROLE,
)

DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
DEFAULT_UPLOAD_URL_SECONDS = 600
DEFAULT_PROCESSING_MAX_BYTES = 100 * 1024 * 1024
PARSER_VERSION = "docling-2.121"
CHUNKER_VERSION = "docling-hybrid-line-v1"
PREVIEW_SCHEMA_VERSION = 1
PREVIEW_RENDERER_VERSION = "webp-v1"
DEFAULT_PREVIEW_MAX_SOURCE_BYTES = 100 * 1024 * 1024
DEFAULT_PREVIEW_MAX_PAGES = 50
DEFAULT_PREVIEW_MAX_DIMENSION = 1_600
DEFAULT_PREVIEW_WEBP_QUALITY = 80

ARTIFACT_COLLECTION_KIND = "conversation_artifacts"
ARTIFACT_COLLECTION_TITLE = "My documents"
ARTIFACT_MIME_TYPE = "text/markdown"
ARTIFACT_DOCUMENT_TYPE = "markdown"

PreviewRepresentation = Literal["original", "image", "pages"]


class IdentityServiceError(Exception):
    """Base exception for identity and authorization failures."""


class IdentityNotFoundError(IdentityServiceError):
    """Raised when a requested user, tenant, role, or connector does not exist."""


class IdentityConflictError(IdentityServiceError):
    """Raised when a unique identity or membership already exists."""


class IdentityInactiveError(IdentityServiceError):
    """Raised when an identity exists but is not active."""


class AuthorizationError(IdentityServiceError):
    """Raised when an identity lacks the required tenant permission."""


class AuthenticationError(IdentityServiceError):
    """Raised when an internal access token or upstream identity is invalid."""


class IdentityProviderUnavailableError(IdentityServiceError):
    """Raised when a configured external identity provider cannot be reached."""


class AdministrationError(Exception):
    """Base exception for governed administration failures."""


class AdminNotFoundError(AdministrationError):
    """Raised when a tenant-scoped administration record is unavailable."""


class AdminConflictError(AdministrationError):
    """Raised when an administration write conflicts with durable state."""


class AdminValidationError(AdministrationError):
    """Raised when an administration input or state transition is invalid."""


class AdminExternalUnavailableError(AdministrationError):
    """Raised when a configured external source cannot be reached."""


class ConnectionAuthorizationRequiredError(AdministrationError):
    """Raised when a Connection's grant is gone and someone must reconnect.

    Distinct from a validation failure: nothing about the request is wrong, and
    no retry helps until a person completes the provider's flow again.

    It carries the state it implies, because raising this rolls back the
    transaction that discovered it — the caller has to write the state down in
    a transaction of its own, or the next request would rediscover the same
    failure and the UI would never learn to offer a reconnect.
    """

    def __init__(
        self,
        message: str,
        *,
        status: str = CONNECTION_REAUTH_REQUIRED,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail or message


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Resolved identity used at service and retrieval permission boundaries.

    ``permission_codes`` holds everything the caller was granted at tenant
    scope in ``tenant_id``, which includes any Collection capability granted
    tenant-wide. Capabilities granted on one Collection are deliberately absent:
    those are resolved per resource by ``AuthorizationService``, because a
    context cannot carry one answer for every Collection in the workspace.
    """

    user_id: UUID
    email: str
    display_name: str | None
    tenant_id: UUID | None
    permission_codes: tuple[str, ...]
    group_ids: tuple[UUID, ...]
    role_codes: tuple[str, ...] = ()
    platform_permissions: tuple[str, ...] = ()

    @property
    def is_enterprise_user(self) -> bool:
        return self.tenant_id is not None

    def has_permissions(self, *permission_codes: str) -> bool:
        required = {_permission_code(code) for code in permission_codes}
        return required.issubset(self.permission_codes)

    def has_platform_permissions(self, *permission_codes: str) -> bool:
        required = {_permission_code(code) for code in permission_codes}
        return required.issubset(self.platform_permissions)


@dataclass(frozen=True, slots=True)
class JwtClaims:
    """Signed access-token claims trusted at the HTTP authentication boundary."""

    user_id: UUID
    email: str
    active_tenant_id: UUID
    permissions: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    platform_permissions: tuple[str, ...] = ()

    def has_permission(self, permission_code: str) -> bool:
        return _permission_code(permission_code) in self.permissions


@dataclass(frozen=True, slots=True)
class VerifiedGoogleIdentity:
    """Identity emitted only by an OAuth verifier after email verification."""

    email: str
    display_name: str | None


@dataclass(frozen=True, slots=True)
class AuthorizationStart:
    """Where to send the browser for consent, and the value it returns with."""

    authorization_url: str
    #: Echoed back to the opener so a page cannot be fooled by a stray message.
    nonce: str


@dataclass(frozen=True, slots=True)
class CompletedAuthorization:
    """One verified provider callback, resolved to the identity that began it."""

    pending: PendingAuthorization
    tenant_id: UUID
    user_id: UUID
    connection_id: UUID | None


@dataclass(frozen=True, slots=True)
class TenantMembershipSummary:
    """One active tenant membership returned after authentication."""

    tenant_id: UUID
    tenant_code: str
    tenant_name: str
    role_codes: tuple[str, ...]
    permissions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthenticationSession:
    """Issued bearer token together with the caller's active workspace context."""

    access_token: str
    expires_at: datetime
    user_id: UUID
    email: str
    display_name: str | None
    active_tenant_id: UUID
    permissions: tuple[str, ...]
    tenants: tuple[TenantMembershipSummary, ...]
    platform_permissions: tuple[str, ...] = ()


SandboxSessionStatus = Literal["active", "expired", "closed"]


@dataclass(frozen=True, slots=True)
class SandboxManifestResource:
    """A durable, provider-neutral input selected for one sandbox workspace."""

    resource_id: str
    name: str
    mime_type: str
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.resource_id, self.name, self.mime_type)):
            raise ValueError("sandbox manifest resource fields must not be blank")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("sandbox manifest resource size must not be negative")


@dataclass(frozen=True, slots=True)
class SandboxProviderFile:
    """A provider file reference retained only inside sandbox runtime state."""

    id: str
    name: str
    resource_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("sandbox provider file fields must not be blank")


@dataclass(frozen=True, slots=True)
class SandboxSessionState:
    """Recovery state for one tenant-scoped conversation sandbox."""

    id: UUID
    provider: str
    status: SandboxSessionStatus
    manifest: tuple[SandboxManifestResource, ...] = ()
    environment_id: str | None = None
    materialized_files: tuple[SandboxProviderFile, ...] = ()
    observed_files: tuple[SandboxProviderFile, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("sandbox provider must not be blank")
        if self.status not in {"active", "expired", "closed"}:
            raise ValueError("sandbox session status is invalid")
        if self.environment_id is not None and not self.environment_id.strip():
            raise ValueError("sandbox environment id must not be blank")


@dataclass(frozen=True, slots=True)
class CanonicalDocumentContent:
    """Canonical source item and chunks produced for one stored document."""

    item: DocumentItem
    chunks: tuple[Chunk, ...]


@runtime_checkable
class StoredFileContent(Protocol):
    """Raw-source boundary consumed by the chat document index pipeline."""

    async def canonicalize(
        self,
        document: Item,
        *,
        access: AuthContext,
    ) -> CanonicalDocumentContent: ...

    async def direct_file_data(
        self,
        document: Item,
        *,
        expires_seconds: int,
    ) -> str: ...


class DocumentServiceError(Exception):
    """Base exception for durable document service failures."""


class DocumentNotFoundError(DocumentServiceError):
    """Raised for missing and inaccessible documents to prevent enumeration."""


class InvalidDocumentStateError(DocumentServiceError):
    """Raised when a lifecycle or lineage transition is invalid."""


class DocumentProcessingError(RuntimeError):
    """Raised when an Item's durable source cannot be prepared for indexing."""


class DocumentUnavailableError(DocumentProcessingError):
    """Raised when an authorized Item's durable source is unavailable."""


class ArtifactValidationError(DocumentServiceError):
    """Raised when an artifact request or state transition is invalid."""


class NativeUploadError(RuntimeError):
    """Base error for a native document upload request."""


class UploadTooLargeError(NativeUploadError):
    pass


class UploadConflictError(NativeUploadError):
    pass


class UploadValidationError(NativeUploadError):
    pass


class PreviewGenerationError(RuntimeError):
    """Raised when a supported source cannot produce a valid preview."""


@runtime_checkable
class AsyncUploadStream(Protocol):
    """Framework-neutral async byte stream accepted by upload services."""

    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class UploadTarget:
    mode: Literal["presigned"]
    request: PresignedRequest


@dataclass(frozen=True, slots=True)
class UploadStart:
    item: Item
    upload: ItemUpload
    upload_required: bool
    target: UploadTarget | None


@dataclass(frozen=True, slots=True)
class CollectionUpload:
    """A retry-safe upload record created under a governed collection."""

    item: Item
    created: bool


@dataclass(frozen=True, slots=True)
class RenderedPreviewAsset:
    """An in-memory WebP rendition awaiting durable storage."""

    data: bytes
    content_type: str
    width: int
    height: int
    page: int | None = None


@dataclass(frozen=True, slots=True)
class RenderedPreview:
    """Bounded preview assets produced from one original source."""

    representation: PreviewRepresentation
    assets: tuple[RenderedPreviewAsset, ...] = ()
    page_count: int | None = None
    truncated: bool = False


class PreviewAsset(BaseModel):
    """Durable metadata for one derived presentation object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    page: int | None = Field(default=None, ge=1)


class PreviewManifest(BaseModel):
    """Versioned internal record of renditions derived from one original."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = PREVIEW_SCHEMA_VERSION
    renderer_version: str = PREVIEW_RENDERER_VERSION
    source_version: str = Field(min_length=1)
    representation: PreviewRepresentation
    assets: tuple[PreviewAsset, ...] = ()
    page_count: int | None = Field(default=None, ge=1)
    truncated: bool = False

    @model_validator(mode="after")
    def _validate_assets(self) -> PreviewManifest:
        pages = [asset.page for asset in self.assets if asset.page is not None]
        if len(pages) != len(set(pages)):
            raise ValueError("preview asset pages must be unique")
        if self.representation == "original" and self.assets:
            raise ValueError("original previews cannot contain derived assets")
        if self.representation != "original" and not self.assets:
            raise ValueError("derived previews require at least one asset")
        if self.page_count is not None and any(
            page > self.page_count for page in pages
        ):
            raise ValueError("preview asset page exceeds the source page count")
        return self


class PreviewOriginal(BaseModel):
    """Permission-checked access to the authoritative source object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    file_name: str
    content_type: str
    size_bytes: int = Field(ge=0)


class ResolvedPreviewAsset(BaseModel):
    """Short-lived, client-facing access to one derived rendition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    content_type: str
    size_bytes: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    page: int | None = Field(default=None, ge=1)


class KnowledgePreviewView(BaseModel):
    """Consistent UX representation for an authorized knowledge asset.

    Citation spans use the same one-based ``page`` values as assets and
    normalized top-left bounding boxes, allowing the UI to highlight a cited
    region without adding presentation data to chunks or the vector index.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    representation: PreviewRepresentation
    original: PreviewOriginal
    assets: tuple[ResolvedPreviewAsset, ...] = ()
    page_count: int | None = Field(default=None, ge=1)
    truncated: bool = False
    coordinate_space: Literal["normalized_top_left"] = "normalized_top_left"


def _permission_code(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ValueError("permission code must not be blank")
    if len(normalized) > 64:
        raise ValueError("permission code must be at most 64 characters")
    return normalized


def require_tenant_permission(
    context: AuthContext,
    *permission_codes: str,
) -> UUID:
    """Return the trusted tenant after enforcing one tenant capability."""

    if context.tenant_id is None:
        raise AuthorizationError("an active tenant membership is required")
    if permission_codes and not context.has_permissions(*permission_codes):
        required = ", ".join(sorted(permission_codes))
        raise AuthorizationError(f"missing required permissions: {required}")
    return context.tenant_id


def require_platform_permission(
    context: AuthContext,
    *permission_codes: str,
) -> None:
    """Reject a platform operation the actor holds no platform role for.

    Platform capability never implies tenant capability: administering the
    platform and reading a workspace's knowledge are separate grants.
    """

    if not context.has_platform_permissions(*permission_codes):
        required = ", ".join(sorted(permission_codes))
        raise AuthorizationError(f"missing required platform permissions: {required}")


def normalize_required_text(value: str, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise AdminValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise AdminValidationError(
            f"{field_name} must be at most {max_length} characters"
        )
    return normalized


def normalize_code(value: str, field_name: str, max_length: int = 64) -> str:
    return normalize_required_text(value, field_name, max_length).casefold()


def normalize_codes(
    values: Iterable[str],
    field_name: str,
    max_length: int = 64,
) -> list[str]:
    return sorted({normalize_code(value, field_name, max_length) for value in values})


def normalize_page(page: int, page_size: int) -> tuple[int, int, int]:
    if page < 1:
        raise AdminValidationError("page must be at least 1")
    if not 1 <= page_size <= 100:
        raise AdminValidationError("page_size must be between 1 and 100")
    return page, page_size, (page - 1) * page_size


def timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = [
    "ACCESS_MANAGE_PERMISSION",
    "ACTIVE_STATUS",
    "ARTIFACT_COLLECTION_KIND",
    "ARTIFACT_COLLECTION_TITLE",
    "ARTIFACT_DOCUMENT_TYPE",
    "ARTIFACT_MIME_TYPE",
    "AUDIT_READ_PERMISSION",
    "AdminConflictError",
    "AdminExternalUnavailableError",
    "AdminNotFoundError",
    "AdminValidationError",
    "AdministrationError",
    "ArtifactValidationError",
    "AsyncUploadStream",
    "AuthContext",
    "AuthenticationError",
    "AuthenticationSession",
    "AuthorizationError",
    "AuthorizationStart",
    "CHUNKER_VERSION",
    "COLLECTION_DELETE_PERMISSION",
    "COLLECTION_EDITOR_ROLE",
    "COLLECTION_OWNER_ROLE",
    "COLLECTION_READ_PERMISSION",
    "COLLECTION_ROLE_CODES",
    "COLLECTION_SCOPE",
    "COLLECTION_SHARE_PERMISSION",
    "COLLECTION_UPDATE_PERMISSION",
    "COLLECTION_VIEWER_ROLE",
    "CONNECTION_CONNECTED",
    "CONNECTION_DISCONNECTED",
    "CONNECTION_DRAFT",
    "CONNECTION_ERROR",
    "CONNECTION_EXPIRED",
    "CONNECTION_NEEDS_AUTHORIZATION",
    "CONNECTION_REAUTH_REQUIRED",
    "CONNECTION_REVOKED",
    "CONNECTION_STATUSES",
    "CanonicalDocumentContent",
    "CollectionUpload",
    "CompletedAuthorization",
    "ConnectionAuthorizationRequiredError",
    "DEFAULT_MAX_UPLOAD_BYTES",
    "DEFAULT_PREVIEW_MAX_DIMENSION",
    "DEFAULT_PREVIEW_MAX_PAGES",
    "DEFAULT_PREVIEW_MAX_SOURCE_BYTES",
    "DEFAULT_PREVIEW_WEBP_QUALITY",
    "DEFAULT_PROCESSING_MAX_BYTES",
    "DEFAULT_UPLOAD_URL_SECONDS",
    "DocumentNotFoundError",
    "DocumentProcessingError",
    "DocumentServiceError",
    "DocumentUnavailableError",
    "GROUP_MANAGE_PERMISSION",
    "INACTIVE_STATUS",
    "ITEM_MANAGE_PERMISSION",
    "IdentityConflictError",
    "IdentityInactiveError",
    "IdentityNotFoundError",
    "IdentityProviderUnavailableError",
    "IdentityServiceError",
    "InvalidDocumentStateError",
    "JwtClaims",
    "KNOWLEDGE_READ_PERMISSION",
    "KnowledgePreviewView",
    "MESSAGE_ITEM_RELATIONS",
    "NativeUploadError",
    "OWNER_TENANT",
    "OWNER_TYPES",
    "OWNER_USER",
    "PARSER_VERSION",
    "PERMISSIONS_BY_CODE",
    "PERMISSION_CATALOG",
    "PLATFORM_ADMIN_ROLE",
    "PLATFORM_AUDIT_READ_PERMISSION",
    "PLATFORM_HEALTH_READ_PERMISSION",
    "PLATFORM_SCOPE",
    "PLATFORM_TENANT_READ_PERMISSION",
    "PLATFORM_USER_READ_PERMISSION",
    "PREVIEW_RENDERER_VERSION",
    "PREVIEW_SCHEMA_VERSION",
    "PermissionDefinition",
    "PreviewAsset",
    "PreviewGenerationError",
    "PreviewManifest",
    "PreviewOriginal",
    "PreviewRepresentation",
    "ROLE_MANAGE_PERMISSION",
    "ROLE_SCOPES",
    "RUNNABLE_SOURCE_STATUSES",
    "RenderedPreview",
    "RenderedPreviewAsset",
    "ResolvedPreviewAsset",
    "RoleDefinition",
    "SOURCE_CONNECTION_REQUIRED",
    "SOURCE_DISABLED",
    "SOURCE_FAILED",
    "SOURCE_MANAGE_PERMISSION",
    "SOURCE_PAUSED",
    "SOURCE_READY",
    "SOURCE_STATUSES",
    "SYSTEM_ROLES",
    "SYSTEM_ROLES_BY_CODE",
    "StoredFileContent",
    "TENANT_ADMIN_ROLE",
    "TENANT_MANAGE_PERMISSION",
    "TENANT_MEMBER_ROLE",
    "TENANT_READ_PERMISSION",
    "TENANT_SCOPE",
    "TenantMembershipSummary",
    "USER_MANAGE_PERMISSION",
    "UploadConflictError",
    "UploadStart",
    "UploadTarget",
    "UploadTooLargeError",
    "UploadValidationError",
    "VerifiedGoogleIdentity",
    "normalize_code",
    "normalize_codes",
    "normalize_page",
    "normalize_required_text",
    "require_platform_permission",
    "require_tenant_permission",
    "timestamp",
]
