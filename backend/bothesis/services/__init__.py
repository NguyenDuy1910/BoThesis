"""Public contracts and primary database-backed services for BoThesis.

Service modules contain only their primary service class. Contexts, DTOs,
errors, and shared constants live here so callers use one stable boundary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from bothesis.db.models import Document
from bothesis.document_index.raw_storage import PresignedRequest
from bothesis.knowledge.protocol import CitationSpan

ACTIVE_STATUS = "active"
INACTIVE_STATUS = "inactive"
ADMIN_PERMISSION = "admin"
LOCAL_DOCUMENT_ORIGINS = frozenset({"upload", "generated"})
MESSAGE_DOCUMENT_RELATIONS = frozenset({"attachment", "reference", "output"})
KNOWLEDGE_READ_PERMISSION = "knowledge.read"
SOURCE_MANAGE_PERMISSION = "source.manage"
USER_MANAGE_PERMISSION = "user.manage"
ROLE_MANAGE_PERMISSION = "role.manage"
GROUP_MANAGE_PERMISSION = "group.manage"
TENANT_MANAGE_PERMISSION = "tenant.manage"
ACCESS_MANAGE_PERMISSION = "access.manage"
AUDIT_READ_PERMISSION = "audit.read"
DOCUMENT_MANAGE_PERMISSION = "document.manage"
ADMIN_PERMISSION_CATALOG = (
    (ADMIN_PERMISSION, "Full administration access"),
    (ACCESS_MANAGE_PERMISSION, "Review access requests and manage resource access"),
    (AUDIT_READ_PERMISSION, "Read tenant administration audit events"),
    (DOCUMENT_MANAGE_PERMISSION, "Manage tenant document lifecycle and indexing"),
    (GROUP_MANAGE_PERMISSION, "Manage groups and group membership"),
    (KNOWLEDGE_READ_PERMISSION, "Read tenant knowledge through permission filters"),
    (ROLE_MANAGE_PERMISSION, "Manage roles and permission assignments"),
    (SOURCE_MANAGE_PERMISSION, "Manage data sources, scopes, and ingestion"),
    (TENANT_MANAGE_PERMISSION, "Manage tenant profile and settings"),
    (USER_MANAGE_PERMISSION, "Manage users and tenant membership"),
)
UPLOAD_STATUSES = frozenset({"not_applicable", "pending", "available", "failed"})
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_DATABASE_BLOB_BYTES = 20 * 1024 * 1024
DEFAULT_UPLOAD_URL_SECONDS = 600


class AuthServiceError(Exception):
    """Base exception for identity and authorization failures."""


class IdentityNotFoundError(AuthServiceError):
    """Raised when a requested user, tenant, role, or connector does not exist."""


class IdentityConflictError(AuthServiceError):
    """Raised when a unique identity or membership already exists."""


class IdentityInactiveError(AuthServiceError):
    """Raised when an identity exists but is not active."""


class AuthorizationError(AuthServiceError):
    """Raised when an identity lacks the required tenant permission."""


class AdminServiceError(Exception):
    """Base exception for tenant administration failures."""


class AdminNotFoundError(AdminServiceError):
    """Raised when a tenant-scoped administration record is unavailable."""


class AdminConflictError(AdminServiceError):
    """Raised when an administration write conflicts with durable state."""


class AdminValidationError(AdminServiceError):
    """Raised when an administration input or state transition is invalid."""


class AdminExternalUnavailableError(AdminServiceError):
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
    principal_tokens: tuple[str, ...]

    @property
    def is_enterprise_user(self) -> bool:
        return self.tenant_id is not None

    @property
    def is_admin(self) -> bool:
        return ADMIN_PERMISSION in self.permission_codes

    def has_permissions(self, *permission_codes: str) -> bool:
        required = {_permission_code(code) for code in permission_codes}
        return self.is_admin or required.issubset(self.permission_codes)


class DocumentServiceError(Exception):
    """Base exception for durable document service failures."""


class DocumentNotFoundError(DocumentServiceError):
    """Raised for missing and inaccessible documents to prevent enumeration."""


class InvalidDocumentStateError(DocumentServiceError):
    """Raised when a lifecycle or lineage transition is invalid."""


@dataclass(frozen=True, slots=True)
class DocumentChunkInput:
    """Canonical chunk content written to PostgreSQL before vector indexing."""

    content: str
    element_id: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    token_count: int | None = None
    start_page_number: int | None = None
    end_page_number: int | None = None
    heading_path: tuple[str, ...] | None = None
    citation_spans: tuple[CitationSpan, ...] = ()
    metadata: Mapping[str, Any] | None = None


class UploadServiceError(RuntimeError):
    """Base error for a document upload request."""


class UploadTooLargeError(UploadServiceError):
    pass


class UploadConflictError(UploadServiceError):
    pass


class UploadValidationError(UploadServiceError):
    pass


@dataclass(frozen=True, slots=True)
class UploadTarget:
    mode: Literal["presigned", "api"]
    request: PresignedRequest


@dataclass(frozen=True, slots=True)
class UploadStart:
    document: Document
    upload_required: bool
    target: UploadTarget | None


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
    return sorted(
        {normalize_code(value, field_name, max_length) for value in values}
    )


def normalize_page(page: int, page_size: int) -> tuple[int, int, int]:
    if page < 1:
        raise AdminValidationError("page must be at least 1")
    if not 1 <= page_size <= 100:
        raise AdminValidationError("page_size must be between 1 and 100")
    return page, page_size, (page - 1) * page_size


def timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# Import primary service classes only after their contracts are defined. The
# service modules import these contracts from this package during initialization.
from bothesis.services.auth import AuthService  # noqa: E402
from bothesis.services.document import DocumentService  # noqa: E402
from bothesis.services.conversation import ConversationService  # noqa: E402
from bothesis.services.upload import UploadService  # noqa: E402
from bothesis.services.audit import AuditService  # noqa: E402
from bothesis.services.datasources import DatasourceService  # noqa: E402
from bothesis.services.access_requests import AccessRequestService  # noqa: E402
from bothesis.services.acl import AclService  # noqa: E402
from bothesis.services.admin_documents import AdminDocumentService  # noqa: E402
from bothesis.services.groups import GroupService  # noqa: E402
from bothesis.services.roles import RoleService  # noqa: E402
from bothesis.services.tenants import TenantService  # noqa: E402
from bothesis.services.users import UserService  # noqa: E402
from bothesis.services.admin import AdminService  # noqa: E402

__all__ = [
    "ACTIVE_STATUS",
    "ACCESS_MANAGE_PERMISSION",
    "ADMIN_PERMISSION_CATALOG",
    "ADMIN_PERMISSION",
    "AUDIT_READ_PERMISSION",
    "AccessRequestService",
    "AclService",
    "AdminConflictError",
    "AdminDocumentService",
    "AdminExternalUnavailableError",
    "AdminNotFoundError",
    "AdminService",
    "AdminServiceError",
    "AdminValidationError",
    "AuditService",
    "AuthContext",
    "AuthService",
    "AuthServiceError",
    "AuthorizationError",
    "ConversationService",
    "DEFAULT_MAX_DATABASE_BLOB_BYTES",
    "DEFAULT_MAX_UPLOAD_BYTES",
    "DEFAULT_UPLOAD_URL_SECONDS",
    "DocumentChunkInput",
    "DocumentNotFoundError",
    "DocumentService",
    "DocumentServiceError",
    "DOCUMENT_MANAGE_PERMISSION",
    "DatasourceService",
    "GROUP_MANAGE_PERMISSION",
    "GroupService",
    "IdentityConflictError",
    "IdentityInactiveError",
    "IdentityNotFoundError",
    "INACTIVE_STATUS",
    "InvalidDocumentStateError",
    "KNOWLEDGE_READ_PERMISSION",
    "LOCAL_DOCUMENT_ORIGINS",
    "MESSAGE_DOCUMENT_RELATIONS",
    "ROLE_MANAGE_PERMISSION",
    "RoleService",
    "SOURCE_MANAGE_PERMISSION",
    "TENANT_MANAGE_PERMISSION",
    "TenantService",
    "UPLOAD_STATUSES",
    "UploadConflictError",
    "UploadService",
    "UploadServiceError",
    "UploadStart",
    "UploadTarget",
    "UploadTooLargeError",
    "UploadValidationError",
    "USER_MANAGE_PERMISSION",
    "UserService",
    "normalize_code",
    "normalize_codes",
    "normalize_page",
    "normalize_required_text",
    "require_tenant_permission",
    "timestamp",
]
