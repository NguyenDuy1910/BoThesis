"""Public contracts and primary database-backed services for BoThesis.

Service modules contain only their primary service class. Contexts, DTOs,
errors, and shared constants live here so callers use one stable boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from bothesis.db.models import Document
from bothesis.document_index.raw_storage import PresignedRequest

ACTIVE_STATUS = "active"
INACTIVE_STATUS = "inactive"
ADMIN_PERMISSION = "admin"
LOCAL_DOCUMENT_ORIGINS = frozenset({"upload", "generated"})
MESSAGE_DOCUMENT_RELATIONS = frozenset({"attachment", "reference", "output"})
KNOWLEDGE_READ_PERMISSION = "knowledge.read"
SOURCE_MANAGE_PERMISSION = "source.manage"
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
    token_count: int | None = None
    start_page_number: int | None = None
    end_page_number: int | None = None
    heading_path: tuple[str, ...] | None = None
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


# Import primary service classes only after their contracts are defined. The
# service modules import these contracts from this package during initialization.
from bothesis.services.auth import AuthService  # noqa: E402
from bothesis.services.document import DocumentService  # noqa: E402
from bothesis.services.conversation import ConversationService  # noqa: E402
from bothesis.services.upload import UploadService  # noqa: E402

__all__ = [
    "ACTIVE_STATUS",
    "ADMIN_PERMISSION",
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
    "IdentityConflictError",
    "IdentityInactiveError",
    "IdentityNotFoundError",
    "INACTIVE_STATUS",
    "InvalidDocumentStateError",
    "KNOWLEDGE_READ_PERMISSION",
    "LOCAL_DOCUMENT_ORIGINS",
    "MESSAGE_DOCUMENT_RELATIONS",
    "SOURCE_MANAGE_PERMISSION",
    "UPLOAD_STATUSES",
    "UploadConflictError",
    "UploadService",
    "UploadServiceError",
    "UploadStart",
    "UploadTarget",
    "UploadTooLargeError",
    "UploadValidationError",
]
