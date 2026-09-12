"""HTTP bearer-token extraction and trusted Google identity hand-off."""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from bothesis.services import AuthenticationError
from bothesis.services.identity_access.jwt_tokens import JwtTokenService


class JwtAuthenticationMiddleware(BaseHTTPMiddleware):
    """Verify a bearer token once and make only its validated claims request-local."""

    def __init__(self, app, *, tokens: JwtTokenService) -> None:
        super().__init__(app)
        self._tokens = tokens

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        authorization = request.headers.get("Authorization")
        if authorization is None:
            return await call_next(request)
        scheme, separator, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not separator or not token.strip():
            return _unauthorized("Authorization must use the Bearer scheme")
        try:
            request.state.jwt_claims = self._tokens.verify(token.strip())
        except AuthenticationError as exc:
            return _unauthorized(str(exc))
        return await call_next(request)


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": detail})


__all__ = ["JwtAuthenticationMiddleware"]
