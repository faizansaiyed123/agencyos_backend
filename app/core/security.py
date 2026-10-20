"""Password hashing, JWT access tokens and opaque random tokens."""

import hashlib
import secrets
import uuid
from datetime import timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import Unauthorized

JWT_ALGORITHM = "HS256"


@lru_cache
def _hasher() -> PasswordHasher:
    s = get_settings()
    return PasswordHasher(time_cost=s.argon2_time_cost, memory_cost=s.argon2_memory_kib)


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-timing-equalisation")


def burn_password_check(password: str) -> None:
    """Spend the same time as a real verification (unknown-email timing side channel)."""
    verify_password(_dummy_hash(), password)


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID) -> tuple[str, int]:
    """Returns (token, expires_in_seconds). The role is deliberately NOT in the token;
    it is read from the database on every request so role changes apply immediately."""
    s = get_settings()
    now = utcnow()
    ttl = timedelta(minutes=s.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "typ": "access",
    }
    token = jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)
    return token, int(ttl.total_seconds())


def decode_access_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (user_id, org_id) or raises Unauthorized."""
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub", "org", "typ"]},
        )
        if payload["typ"] != "access":
            raise Unauthorized("Invalid token")
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["org"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise Unauthorized("Invalid or expired token") from exc


def create_mfa_pending_token(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    """Issued after a correct password when MFA is enabled — proves 'password was
    correct' without granting any API access. Deliberately a distinct `typ` from
    the real access token so `decode_access_token` can never accept one, even if
    an endpoint forgot to check."""
    s = get_settings()
    now = utcnow()
    ttl = timedelta(minutes=s.mfa_pending_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "typ": "mfa_pending",
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_mfa_pending_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub", "org", "typ"]},
        )
        if payload["typ"] != "mfa_pending":
            raise Unauthorized("Invalid or expired MFA session", code="invalid_mfa_pending_token")
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["org"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise Unauthorized(
            "Invalid or expired MFA session", code="invalid_mfa_pending_token"
        ) from exc


def new_opaque_token() -> tuple[str, str]:
    """Returns (raw_token, sha256_hash). Only the hash is ever stored.
    SHA-256 is appropriate because the token has 256 bits of entropy."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
