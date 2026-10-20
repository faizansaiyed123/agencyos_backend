"""Symmetric encryption for secrets that must be readable by the app at runtime
(TOTP seeds today; a webhook signing key later) — as opposed to passwords, which
are hashed one-way in security.py and never decrypted.

Uses Fernet (AES-128-CBC + HMAC-SHA256, authenticated) from the `cryptography`
library. The key is a separate setting from JWT_SECRET on purpose: rotating one
must never silently invalidate the other.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.errors import AppError


class DecryptionError(AppError):
    status_code = 500
    code = "decryption_failed"
    title = "Stored secret could not be decrypted"


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().mfa_encryption_key.get_secret_value().encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError() from exc
