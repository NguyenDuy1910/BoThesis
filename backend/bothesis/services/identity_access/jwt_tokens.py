"""Issue and verify the internal HS256 access-token contract."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from bothesis.services import AuthenticationError, AuthContext, JwtClaims


class JwtTokenService:
    """Own signed access tokens without exposing the signing secret to callers."""

    def __init__(
        self,
        *,
        secret: str | None,
        issuer: str,
        audience: str,
        expires_in_seconds: int,
    ) -> None:
        self._secret = secret.encode("utf-8") if secret else None
        self._issuer = issuer
        self._audience = audience
        self._expires_in_seconds = expires_in_seconds

    def issue(self, context: AuthContext) -> tuple[str, datetime]:
        """Sign an access token for one already-authorized active tenant."""

        if context.tenant_id is None:
            raise AuthenticationError("an active tenant is required to issue a token")
        secret = self._secret_or_error()
        issued_at = int(time.time())
        expires_at = issued_at + self._expires_in_seconds
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(context.user_id),
            "user_id": str(context.user_id),
            "email": context.email,
            "active_tenant_id": str(context.tenant_id),
            "permissions": list(context.permission_codes),
            "platform_scopes": list(context.platform_scopes),
            "iat": issued_at,
            "exp": expires_at,
            "jti": str(uuid4()),
        }
        encoded_header = _encode_json(header)
        encoded_payload = _encode_json(payload)
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
        return (
            f"{encoded_header}.{encoded_payload}.{_encode_segment(signature)}",
            datetime.fromtimestamp(expires_at, UTC),
        )

    def verify(self, token: str) -> JwtClaims:
        """Validate signature and standard claims before an HTTP request is trusted."""

        secret = self._secret_or_error()
        parts = token.split(".")
        if len(parts) != 3 or not all(parts):
            raise AuthenticationError("access token is malformed")
        encoded_header, encoded_payload, encoded_signature = parts
        try:
            header = _decode_json(encoded_header)
            payload = _decode_json(encoded_payload)
            actual_signature = _decode_segment(encoded_signature)
        except (UnicodeDecodeError, ValueError, binascii.Error) as exc:
            raise AuthenticationError("access token is malformed") from exc
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise AuthenticationError("access token uses an unsupported algorithm")
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        expected_signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(actual_signature, expected_signature):
            raise AuthenticationError("access token signature is invalid")
        return _claims_from_payload(payload, issuer=self._issuer, audience=self._audience)

    def _secret_or_error(self) -> bytes:
        if self._secret is None or len(self._secret) < 32:
            raise AuthenticationError(
                "BOTHESIS_AUTH_JWT_SECRET must contain at least 32 bytes"
            )
        return self._secret


def _encode_json(value: dict[str, object]) -> str:
    return _encode_segment(json.dumps(value, separators=(",", ":"), sort_keys=True).encode())


def _encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_json(value: str) -> dict[str, object]:
    decoded = json.loads(_decode_segment(value).decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("JWT segment must contain an object")
    return decoded


def _decode_segment(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _claims_from_payload(
    payload: dict[str, object], *, issuer: str, audience: str
) -> JwtClaims:
    if payload.get("iss") != issuer or payload.get("aud") != audience:
        raise AuthenticationError("access token issuer or audience is invalid")
    try:
        user_id = UUID(_string_claim(payload, "user_id"))
        tenant_id = UUID(_string_claim(payload, "active_tenant_id"))
    except ValueError as exc:
        raise AuthenticationError("access token has an invalid identifier") from exc
    if payload.get("sub") != str(user_id):
        raise AuthenticationError("access token subject is invalid")
    permissions_value = payload.get("permissions")
    if not isinstance(permissions_value, list) or not all(
        isinstance(value, str) and value.strip() for value in permissions_value
    ):
        raise AuthenticationError("access token permissions are invalid")
    permissions = tuple(sorted({value.strip().casefold() for value in permissions_value}))
    scopes_value = payload.get("platform_scopes", [])
    if not isinstance(scopes_value, list) or not all(
        isinstance(value, str) and value.strip() for value in scopes_value
    ):
        raise AuthenticationError("access token platform scopes are invalid")
    platform_scopes = tuple(sorted({value.strip().casefold() for value in scopes_value}))
    issued_at = _timestamp_claim(payload, "iat")
    expires_at = _timestamp_claim(payload, "exp")
    now = int(time.time())
    if expires_at <= now:
        raise AuthenticationError("access token has expired")
    if issued_at > now + 60 or expires_at <= issued_at:
        raise AuthenticationError("access token timestamps are invalid")
    return JwtClaims(
        user_id=user_id,
        email=_string_claim(payload, "email").casefold(),
        active_tenant_id=tenant_id,
        permissions=permissions,
        platform_scopes=platform_scopes,
        issued_at=datetime.fromtimestamp(issued_at, UTC),
        expires_at=datetime.fromtimestamp(expires_at, UTC),
    )


def _string_claim(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise AuthenticationError(f"access token {name} is invalid")
    return value.strip()


def _timestamp_claim(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthenticationError(f"access token {name} is invalid")
    return value


__all__ = ["JwtTokenService"]
