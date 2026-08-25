"""Authenticated encryption for persisted Plugin Connection credentials."""

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

from bothesis.db.models import PluginCredential
from bothesis.services import AdminValidationError


class PluginCredentialService:
    """Encrypt and decrypt secrets with Connection-bound associated data."""

    def __init__(self, session: AsyncSession, encryption_key: str) -> None:
        self._session = session
        self._key = self._decode_key(encryption_key)

    async def store(
        self,
        connection_id: UUID,
        *,
        credential_type: str,
        payload: Mapping[str, Any],
        expires_at: datetime | None = None,
        key_version: str | None = None,
    ) -> PluginCredential:
        normalized_type = credential_type.strip().casefold()
        if not normalized_type or len(normalized_type) > 64:
            raise AdminValidationError("credential type is invalid")
        encoded = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if encoded == b"{}":
            raise AdminValidationError("plugin credentials must not be empty")
        nonce = os.urandom(12)
        encrypted = AESGCM(self._key).encrypt(
            nonce, encoded, self._associated_data(connection_id)
        )
        envelope = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")
        record = await self._session.scalar(
            select(PluginCredential)
            .where(PluginCredential.connection_id == connection_id)
            .with_for_update()
        )
        if record is None:
            record = PluginCredential(
                connection_id=connection_id,
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

    async def resolve(self, connection_id: UUID) -> dict[str, Any]:
        record = await self._session.scalar(
            select(PluginCredential).where(
                PluginCredential.connection_id == connection_id
            )
        )
        if record is None:
            raise LookupError("plugin credentials are not configured")
        try:
            envelope = base64.urlsafe_b64decode(record.encrypted_payload.encode("ascii"))
            nonce, ciphertext = envelope[:12], envelope[12:]
            plaintext = AESGCM(self._key).decrypt(
                nonce, ciphertext, self._associated_data(connection_id)
            )
            payload = json.loads(plaintext)
        except Exception as exc:
            raise RuntimeError("plugin credentials could not be decrypted") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("plugin credential payload is invalid")
        return payload

    @staticmethod
    def _decode_key(value: str) -> bytes:
        normalized = value.strip()
        if not normalized:
            raise RuntimeError("BOTHESIS_PLUGIN_ENCRYPTION_KEY is required")
        padded = normalized + "=" * (-len(normalized) % 4)
        try:
            key = base64.b64decode(
                padded.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        except Exception as exc:
            raise RuntimeError(
                "BOTHESIS_PLUGIN_ENCRYPTION_KEY must be URL-safe base64"
            ) from exc
        if len(key) != 32:
            raise RuntimeError(
                "BOTHESIS_PLUGIN_ENCRYPTION_KEY must decode to exactly 32 bytes"
            )
        return key

    @staticmethod
    def _associated_data(connection_id: UUID) -> bytes:
        return f"bothesis:plugin-credential:{connection_id}".encode("ascii")


__all__ = ["PluginCredentialService"]
