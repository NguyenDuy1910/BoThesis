"""Authenticated encryption for persisted Integration Connection credentials."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import IntegrationCredential
from bothesis.services import AdminValidationError


class IntegrationCredentialService:
    """Encrypt and decrypt secrets with Connection-bound associated data."""

    def __init__(self, session: AsyncSession, encryption_key: str) -> None:
        self._session = session
        self._key = self._decode_key(encryption_key)

    async def store(
        self,
        integration_connection_id: UUID,
        *,
        credential_type: str,
        payload: Mapping[str, Any],
        expires_at: datetime | None = None,
        key_version: str | None = None,
    ) -> IntegrationCredential:
        normalized_type = credential_type.strip().casefold()
        if not normalized_type or len(normalized_type) > 64:
            raise AdminValidationError("credential type is invalid")
        encoded = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if encoded == b"{}":
            raise AdminValidationError("integration credentials must not be empty")
        nonce = os.urandom(12)
        encrypted = AESGCM(self._key).encrypt(
            nonce, encoded, self._associated_data(integration_connection_id)
        )
        envelope = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")
        record = await self._session.scalar(
            select(IntegrationCredential)
            .where(IntegrationCredential.integration_connection_id == integration_connection_id)
            .with_for_update()
        )
        if record is None:
            record = IntegrationCredential(
                integration_connection_id=integration_connection_id,
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

    async def resolve(self, integration_connection_id: UUID) -> dict[str, Any]:
        record = await self._session.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.integration_connection_id == integration_connection_id
            )
        )
        if record is None:
            raise LookupError("integration credentials are not configured")
        try:
            envelope = base64.urlsafe_b64decode(record.encrypted_payload.encode("ascii"))
            nonce, ciphertext = envelope[:12], envelope[12:]
            plaintext = AESGCM(self._key).decrypt(
                nonce, ciphertext, self._associated_data(integration_connection_id)
            )
            payload = json.loads(plaintext)
        except Exception as exc:
            raise RuntimeError("integration credentials could not be decrypted") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("integration credential payload is invalid")
        return payload

    @staticmethod
    def _decode_key(value: str) -> bytes:
        normalized = value.strip()
        if not normalized:
            raise RuntimeError("BOTHESIS_INTEGRATION_ENCRYPTION_KEY is required")
        padded = normalized + "=" * (-len(normalized) % 4)
        try:
            key = base64.b64decode(
                padded.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        except Exception as exc:
            raise RuntimeError(
                "BOTHESIS_INTEGRATION_ENCRYPTION_KEY must be URL-safe base64"
            ) from exc
        if len(key) != 32:
            raise RuntimeError(
                "BOTHESIS_INTEGRATION_ENCRYPTION_KEY must decode to exactly 32 bytes"
            )
        return key

    @staticmethod
    def _associated_data(integration_connection_id: UUID) -> bytes:
        # This persisted AAD namespace is a cryptographic format identifier.
        # Changing it would make credentials encrypted before this rename unreadable.
        return f"bothesis:plugin-credential:{integration_connection_id}".encode("ascii")


__all__ = ["IntegrationCredentialService"]
