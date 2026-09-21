"""Hash and verify first-party account passwords."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


class PasswordCredentialService:
    """Use memory-hard scrypt hashes without storing plaintext credentials."""

    _N = 2**14
    _R = 8
    _P = 1
    _SALT_BYTES = 16
    _KEY_BYTES = 32

    @classmethod
    def hash(cls, password: str) -> str:
        _validate_password(password)
        salt = secrets.token_bytes(cls._SALT_BYTES)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=cls._N,
            r=cls._R,
            p=cls._P,
            dklen=cls._KEY_BYTES,
        )
        encode = base64.urlsafe_b64encode
        return "scrypt$%d$%d$%d$%s$%s" % (
            cls._N,
            cls._R,
            cls._P,
            encode(salt).decode("ascii"),
            encode(digest).decode("ascii"),
        )

    @classmethod
    def verify(cls, password: str, encoded: str) -> bool:
        try:
            algorithm, n, r, p, salt_value, digest_value = encoded.split("$", 5)
            if algorithm != "scrypt":
                return False
            salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
            actual = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(expected),
            )
        except (ValueError, TypeError, UnicodeError):
            return False
        return hmac.compare_digest(actual, expected)


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValueError("password must be between 8 and 128 characters")


__all__ = ["PasswordCredentialService"]
