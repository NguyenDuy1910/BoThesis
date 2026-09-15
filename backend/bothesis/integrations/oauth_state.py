"""Authenticated encryption for the OAuth ``state`` parameter."""

from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from bothesis.integrations import (
    IntegrationAuthorizationError,
    IntegrationConfigurationError,
    PendingAuthorization,
)

_ASSOCIATED_DATA = b"bothesis:integration-authorization-state"
_MAX_STATE_BYTES = 2_048


class OAuthStateCodec:
    """Carry one pending authorization through the provider and back.

    The state is encrypted, not merely signed, because it holds the PKCE code
    verifier: a verifier readable by anything that observes the redirect would
    make PKCE decorative. Authentication of the ciphertext is what rejects a
    forged callback, and the embedded expiry is what stops an old one from
    being replayed.
    """

    def __init__(self, secret: str | None, *, lifetime_seconds: int = 600) -> None:
        self._secret = (secret or "").strip()
        self._lifetime_seconds = lifetime_seconds

    @property
    def configured(self) -> bool:
        return bool(self._secret)

    def issue(self, pending: PendingAuthorization) -> str:
        """Encrypt one pending authorization into an opaque state value."""

        issued_at = datetime.now(UTC)
        payload = {
            "tenant_id": pending.tenant_id,
            "user_id": pending.user_id,
            "provider_key": pending.provider_key,
            "connector_key": pending.connector_key,
            "owner_type": pending.owner_type,
            "connection_id": pending.connection_id,
            "code_verifier": pending.code_verifier,
            "nonce": pending.nonce or secrets.token_urlsafe(16),
            "exp": int(issued_at.timestamp()) + self._lifetime_seconds,
        }
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key()).encrypt(nonce, encoded, _ASSOCIATED_DATA)
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")

    def read(self, state: str) -> PendingAuthorization:
        """Decrypt one state value, or reject it."""

        normalized = (state or "").strip()
        if not normalized or len(normalized) > _MAX_STATE_BYTES:
            raise IntegrationAuthorizationError("authorization state is invalid")
        try:
            envelope = base64.urlsafe_b64decode(
                normalized + "=" * (-len(normalized) % 4)
            )
            plaintext = AESGCM(self._key()).decrypt(
                envelope[:12], envelope[12:], _ASSOCIATED_DATA
            )
            payload: Any = json.loads(plaintext)
        except Exception as exc:
            raise IntegrationAuthorizationError(
                "authorization state is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise IntegrationAuthorizationError("authorization state is invalid")
        expires_at = payload.get("exp")
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or expires_at <= datetime.now(UTC).timestamp()
        ):
            raise IntegrationAuthorizationError("authorization state has expired")
        try:
            return PendingAuthorization(
                tenant_id=_required(payload, "tenant_id"),
                user_id=_required(payload, "user_id"),
                provider_key=_required(payload, "provider_key"),
                connector_key=_required(payload, "connector_key"),
                owner_type=_required(payload, "owner_type"),
                connection_id=_optional(payload, "connection_id"),
                code_verifier=_required(payload, "code_verifier"),
                nonce=_required(payload, "nonce"),
            )
        except ValueError as exc:
            raise IntegrationAuthorizationError(
                "authorization state is invalid"
            ) from exc

    def _key(self) -> bytes:
        if not self._secret:
            raise IntegrationConfigurationError(
                "BOTHESIS_INTEGRATION_OAUTH_STATE_SECRET is not configured"
            )
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=_ASSOCIATED_DATA,
        ).derive(self._secret.encode("utf-8"))


def _required(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"authorization state field is missing: {name}")
    return value


def _optional(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"authorization state field is invalid: {name}")
    return value


__all__ = ["OAuthStateCodec"]
