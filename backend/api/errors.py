"""Translate service failures into HTTP responses at one boundary."""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from bothesis.services import (
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    AuthorizationError,
    DocumentNotFoundError,
    IdentityInactiveError,
    IdentityNotFoundError,
    IdentityServiceError,
    UploadConflictError,
    UploadTooLargeError,
    UploadValidationError,
)
from bothesis.storage import ObjectStorageError

# An authorization failure is a missing credential, not a denied one, when the
# request never carried a trusted identity in the first place.
_UNAUTHENTICATED_MARKERS = (
    "authenticated request context",
    "development user ID",
    "request auth context",
)

_STATUS_BY_ERROR: tuple[tuple[type[Exception], int], ...] = (
    (AdminNotFoundError, status.HTTP_404_NOT_FOUND),
    (IdentityNotFoundError, status.HTTP_404_NOT_FOUND),
    (DocumentNotFoundError, status.HTTP_404_NOT_FOUND),
    (AdminConflictError, status.HTTP_409_CONFLICT),
    (UploadConflictError, status.HTTP_409_CONFLICT),
    (AdminValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (UploadValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (UploadTooLargeError, status.HTTP_413_CONTENT_TOO_LARGE),
    (IdentityInactiveError, status.HTTP_401_UNAUTHORIZED),
    (IdentityServiceError, status.HTTP_401_UNAUTHORIZED),
    (PermissionError, status.HTTP_403_FORBIDDEN),
)

HANDLED_ERRORS: tuple[type[Exception], ...] = (
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
    IdentityServiceError,
    PermissionError,
    AdminExternalUnavailableError,
    ObjectStorageError,
    RuntimeError,
    ValueError,
)


def status_for(exc: Exception) -> int:
    """Map one service failure to the status code the API contract promises."""

    if isinstance(exc, AuthorizationError):
        detail = str(exc)
        if any(marker in detail for marker in _UNAUTHENTICATED_MARKERS):
            return status.HTTP_401_UNAUTHORIZED
        return status.HTTP_403_FORBIDDEN
    for error_type, status_code in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return status_code
    return status.HTTP_503_SERVICE_UNAVAILABLE


def detail_for(exc: Exception) -> str:
    if isinstance(exc, ObjectStorageError):
        return "document storage is temporarily unavailable"
    return str(exc)


async def service_error_response(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": detail_for(exc)},
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach one response shape to every failure the services can raise."""

    for error_type in HANDLED_ERRORS:
        app.add_exception_handler(error_type, service_error_response)


__all__ = [
    "HANDLED_ERRORS",
    "detail_for",
    "register_error_handlers",
    "service_error_response",
    "status_for",
]
