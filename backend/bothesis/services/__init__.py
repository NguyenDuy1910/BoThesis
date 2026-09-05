"""Public contracts and primary database-backed services for BoThesis.

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

from bothesis.connector.protocol import Chunk, DocumentItem
from bothesis.db.models import Item, ItemUpload
from bothesis.storage import PresignedRequest

ACTIVE_STATUS = "active"
INACTIVE_STATUS = "inactive"
ADMIN_PERMISSION = "admin"
MESSAGE_ITEM_RELATIONS = frozenset({"attachment", "reference", "output"})
KNOWLEDGE_READ_PERMISSION = "knowledge.read"
SOURCE_MANAGE_PERMISSION = "source.manage"
USER_MANAGE_PERMISSION = "user.manage"
ROLE_MANAGE_PERMISSION = "role.manage"
GROUP_MANAGE_PERMISSION = "group.manage"
TENANT_MANAGE_PERMISSION = "tenant.manage"
ACCESS_MANAGE_PERMISSION = "access.manage"
AUDIT_READ_PERMISSION = "audit.read"
ITEM_MANAGE_PERMISSION = "item.manage"
ADMIN_PERMISSION_CATALOG = (
    (ADMIN_PERMISSION, "Full administration access"),
    (ACCESS_MANAGE_PERMISSION, "Review access requests and manage resource access"),
    (AUDIT_READ_PERMISSION, "Read tenant administration audit events"),
    (ITEM_MANAGE_PERMISSION, "Manage canonical Item lifecycle and indexing"),
    (GROUP_MANAGE_PERMISSION, "Manage groups and group membership"),
    (KNOWLEDGE_READ_PERMISSION, "Read tenant knowledge through permission filters"),
    (ROLE_MANAGE_PERMISSION, "Manage roles and permission assignments"),
    (SOURCE_MANAGE_PERMISSION, "Manage data sources, scopes, and ingestion"),
    (TENANT_MANAGE_PERMISSION, "Manage tenant profile and settings"),
    (USER_MANAGE_PERMISSION, "Manage users and tenant membership"),
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


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Resolved identity used at service and retrieval permission boundaries."""

    user_id: UUID
    email: str
    display_name: str | None
    tenant_id: UUID | None
    role_id: UUID | None
    role_code: str | None
    permission_codes: tuple[str, ...]
    group_ids: tuple[UUID, ...]

    @property
    def is_enterprise_user(self) -> bool:
        return self.tenant_id is not None

    @property
    def is_admin(self) -> bool:
        return ADMIN_PERMISSION in self.permission_codes

    def has_permissions(self, *permission_codes: str) -> bool:
        required = {_permission_code(code) for code in permission_codes}
        return self.is_admin or required.issubset(self.permission_codes)


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
    def _validate_assets(self) -> "PreviewManifest":
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
    "ADMIN_PERMISSION",
    "ADMIN_PERMISSION_CATALOG",
    "AUDIT_READ_PERMISSION",
    "CHUNKER_VERSION",
    "DEFAULT_MAX_UPLOAD_BYTES",
    "DEFAULT_PREVIEW_MAX_DIMENSION",
    "DEFAULT_PREVIEW_MAX_PAGES",
    "DEFAULT_PREVIEW_MAX_SOURCE_BYTES",
    "DEFAULT_PREVIEW_WEBP_QUALITY",
    "DEFAULT_PROCESSING_MAX_BYTES",
    "DEFAULT_UPLOAD_URL_SECONDS",
    "GROUP_MANAGE_PERMISSION",
    "INACTIVE_STATUS",
    "ITEM_MANAGE_PERMISSION",
    "KNOWLEDGE_READ_PERMISSION",
    "MESSAGE_ITEM_RELATIONS",
    "PARSER_VERSION",
    "PREVIEW_RENDERER_VERSION",
    "PREVIEW_SCHEMA_VERSION",
    "ROLE_MANAGE_PERMISSION",
    "SOURCE_MANAGE_PERMISSION",
    "TENANT_MANAGE_PERMISSION",
    "USER_MANAGE_PERMISSION",
    "AdminConflictError",
    "AdminExternalUnavailableError",
    "AdminNotFoundError",
    "AdministrationError",
    "AdminValidationError",
    "AsyncUploadStream",
    "AuthContext",
    "IdentityServiceError",
    "AuthorizationError",
    "CanonicalDocumentContent",
    "StoredFileContent",
    "CollectionUpload",
    "DocumentNotFoundError",
    "DocumentProcessingError",
    "DocumentServiceError",
    "DocumentUnavailableError",
    "IdentityConflictError",
    "IdentityInactiveError",
    "IdentityNotFoundError",
    "InvalidDocumentStateError",
    "KnowledgePreviewView",
    "PreviewAsset",
    "PreviewGenerationError",
    "PreviewManifest",
    "PreviewOriginal",
    "PreviewRepresentation",
    "RenderedPreview",
    "RenderedPreviewAsset",
    "ResolvedPreviewAsset",
    "UploadConflictError",
    "NativeUploadError",
    "UploadStart",
    "UploadTarget",
    "UploadTooLargeError",
    "UploadValidationError",
    "normalize_code",
    "normalize_codes",
    "normalize_page",
    "normalize_required_text",
    "require_tenant_permission",
    "timestamp",
]
