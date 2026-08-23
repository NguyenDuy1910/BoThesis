"""Authenticated encryption for locally stored connector credentials."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import ConnectorCredential
from bothesis.services import AdminValidationError


class ConnectorCredentialService:
    """Encrypt and decrypt provider credentials with connector-bound AEAD."""

    def __init__(self, session: AsyncSession, encryption_key: str) -> None:
        self._session = session
        self._key = _decode_key(encryption_key)

    async def store(
        self,
        connector_id: int,
        *,
        credential_type: str,
        payload: Mapping[str, Any],
        expires_at: datetime | None = None,
        key_version: str | None = None,
    ) -> ConnectorCredential:
        normalized_type = credential_type.strip().casefold()
        if not normalized_type or len(normalized_type) > 64:
            raise AdminValidationError("credential type is invalid")
        encoded = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if encoded == b"{}":
            raise AdminValidationError("connector credentials must not be empty")
        nonce = os.urandom(12)
        encrypted = AESGCM(self._key).encrypt(
            nonce, encoded, _associated_data(connector_id)
        )
        envelope = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")
        record = await self._session.scalar(
            select(ConnectorCredential)
            .where(ConnectorCredential.connector_id == connector_id)
            .with_for_update()
        )
        if record is None:
            record = ConnectorCredential(
                connector_id=connector_id,
                credential_type=normalized_type,
                encrypted_payload=envelope,
                expires_at=expires_at,
                key_version=key_version,
            )
            self._session.add(record)
        else:
            record.credential_type = normalized_type
            record.encrypted_payload = envelope
            record.expires_at = expires_at
            record.key_version = key_version
        await self._session.flush()
        return record

    async def resolve(self, connector_id: int) -> dict[str, Any]:
        record = await self._session.scalar(
            select(ConnectorCredential).where(
                ConnectorCredential.connector_id == connector_id
            )
        )
        if record is None:
            raise LookupError("connector credentials are not configured")
        try:
            envelope = base64.urlsafe_b64decode(record.encrypted_payload.encode("ascii"))
            nonce, ciphertext = envelope[:12], envelope[12:]
            plaintext = AESGCM(self._key).decrypt(
                nonce, ciphertext, _associated_data(connector_id)
            )
            payload = json.loads(plaintext)
        except Exception as exc:
            raise RuntimeError("connector credentials could not be decrypted") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("connector credential payload is invalid")
        return payload


def _decode_key(value: str) -> bytes:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError("BOTHESIS_CONNECTOR_ENCRYPTION_KEY is required")
    try:
        key = base64.urlsafe_b64decode(normalized.encode("ascii"))
    except Exception as exc:
        raise RuntimeError(
            "BOTHESIS_CONNECTOR_ENCRYPTION_KEY must be URL-safe base64"
        ) from exc
    if len(key) != 32:
        raise RuntimeError(
            "BOTHESIS_CONNECTOR_ENCRYPTION_KEY must decode to exactly 32 bytes"
        )
    return key


def _associated_data(connector_id: int) -> bytes:
    return f"bothesis:connector-credential:{connector_id}".encode("ascii")


__all__ = ["ConnectorCredentialService"]
