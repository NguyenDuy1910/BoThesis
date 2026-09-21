"""Google ID-token verification for the authentication boundary."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

from bothesis.services import (
    AuthenticationError,
    IdentityProviderUnavailableError,
    VerifiedGoogleIdentity,
)

_GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
_DEFAULT_JWKS_CACHE_SECONDS = 3_600


class GoogleIdentityVerifier:
    """Verify a Google Identity Services credential against Google's published keys."""

    def __init__(self, *, client_id: str | None, jwks_url: str) -> None:
        self._client_id = client_id
        self._jwks_url = jwks_url
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._keys_expire_at = 0.0
        self._lock = asyncio.Lock()

    async def verify(self, credential: str) -> VerifiedGoogleIdentity:
        """Return only an email-verified Google identity for this application client."""

        client_id = self._client_id
        if client_id is None:
            raise IdentityProviderUnavailableError("Google sign-in is not configured")
        header, payload, signed = _decode_credential(credential)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise AuthenticationError("Google credential uses an unsupported signing key")
        key = await self._key(header["kid"])
        try:
            signature = _decode_segment(credential.rsplit(".", 1)[1])
        except binascii.Error as exc:
            raise AuthenticationError("Google credential is malformed") from exc
        try:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature as exc:
            raise AuthenticationError("Google credential signature is invalid") from exc
        return _identity_from_claims(payload, client_id=client_id)

    async def _key(self, key_id: str) -> rsa.RSAPublicKey:
        if time.monotonic() < self._keys_expire_at and key_id in self._keys:
            return self._keys[key_id]
        async with self._lock:
            if time.monotonic() >= self._keys_expire_at or key_id not in self._keys:
                await self._refresh_keys()
            key = self._keys.get(key_id)
            if key is None:
                raise AuthenticationError("Google credential signing key is unknown")
            return key

    async def _refresh_keys(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._jwks_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailableError(
                "Google identity verification is temporarily unavailable"
            ) from exc
        try:
            payload = response.json()
            entries = payload["keys"]
            keys = {
                key_id: _rsa_key(entry)
                for entry in entries
                if isinstance(entry, dict)
                and isinstance((key_id := entry.get("kid")), str)
                and entry.get("kty") == "RSA"
                and entry.get("alg") == "RS256"
            }
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise IdentityProviderUnavailableError(
                "Google identity verification returned invalid signing keys"
            ) from exc
        if not keys:
            raise IdentityProviderUnavailableError(
                "Google identity verification returned no signing keys"
            )
        self._keys = keys
        self._keys_expire_at = time.monotonic() + _cache_seconds(
            response.headers.get("Cache-Control")
        )


def _decode_credential(credential: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    parts = credential.split(".")
    if len(parts) != 3 or not all(parts):
        raise AuthenticationError("Google credential is malformed")
    header_segment, payload_segment, _ = parts
    try:
        header = _decode_json(header_segment)
        payload = _decode_json(payload_segment)
    except (UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise AuthenticationError("Google credential is malformed") from exc
    return header, payload, f"{header_segment}.{payload_segment}".encode("ascii")


def _identity_from_claims(
    claims: dict[str, Any], *, client_id: str
) -> VerifiedGoogleIdentity:
    audience = claims.get("aud")
    if isinstance(audience, str):
        audiences = {audience}
    elif isinstance(audience, list) and all(isinstance(value, str) for value in audience):
        audiences = set(audience)
    else:
        audiences = set()
    if client_id not in audiences:
        raise AuthenticationError("Google credential audience is invalid")
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise AuthenticationError("Google credential issuer is invalid")
    if not _truthy_boolean(claims.get("email_verified")):
        raise AuthenticationError("Google account email is not verified")
    expires_at = claims.get("exp")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int) or expires_at <= time.time():
        raise AuthenticationError("Google credential has expired")
    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject.strip() or not isinstance(email, str):
        raise AuthenticationError("Google credential identity is invalid")
    name = claims.get("name")
    return VerifiedGoogleIdentity(
        issuer=str(claims["iss"]),
        subject=subject.strip(),
        email=email,
        display_name=name if isinstance(name, str) and name.strip() else None,
    )


def _rsa_key(entry: dict[str, Any]) -> rsa.RSAPublicKey:
    modulus = int.from_bytes(_decode_segment(_required_string(entry, "n")), "big")
    exponent = int.from_bytes(_decode_segment(_required_string(entry, "e")), "big")
    return rsa.RSAPublicNumbers(exponent, modulus).public_key()


def _decode_json(value: str) -> dict[str, Any]:
    decoded = json.loads(_decode_segment(value).decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("JWT segment must contain an object")
    return decoded


def _decode_segment(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def _required_string(value: dict[str, Any], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Google signing key {name} is invalid")
    return result


def _truthy_boolean(value: object) -> bool:
    return value is True or value == "true"


def _cache_seconds(cache_control: str | None) -> int:
    if cache_control:
        for part in cache_control.split(","):
            name, separator, value = part.strip().partition("=")
            if name == "max-age" and separator and value.isdigit():
                return max(60, int(value))
    return _DEFAULT_JWKS_CACHE_SECONDS


__all__ = ["GoogleIdentityVerifier"]
