"""Idempotency-Key support for mutating endpoints (POST/PATCH/DELETE), modeled on
the same mechanism Stripe's API exposes to clients: a client supplies an
`Idempotency-Key` header; if the same key is replayed, the ORIGINAL response is
returned instead of repeating the side effect (double-submit, a retried request
after a dropped connection, etc.).

Scope: authenticated, org-scoped endpoints only (this table is RLS-protected like
every other tenant table — see the migration). Pre-auth endpoints like signup
already have their own idempotency-equivalent (the unique-email constraint) and
have no org_id to scope by yet.
"""

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ForeignKeyConstraint, Integer, String, UniqueConstraint, Uuid, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import get_settings
from app.core.db import set_org_context
from app.core.errors import AppError
from app.core.models import Base, created_at_col


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], ondelete="CASCADE",
            name="fk_idempotency_keys_org_id_users",
        ),
        UniqueConstraint("org_id", "key", name="uq_idempotency_keys_org_id_key"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(200))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()


class IdempotencyConflict(AppError):
    """Same key, different request body — the client is reusing a key incorrectly."""

    status_code = 409
    code = "idempotency_key_conflict"
    title = "Idempotency-Key was reused with a different request body"


class IdempotencyReplay(Exception):  # noqa: N818 — signals a cached result, not an error path
    """Same key, same request — return the original response instead of re-running."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body


def fingerprint(method: str, path: str, body: bytes) -> str:
    return hashlib.sha256(f"{method}:{path}:".encode() + body).hexdigest()


def check_idempotency_key(db: Session, *, org_id: uuid.UUID, key: str, request_fp: str) -> None:
    """Raises IdempotencyReplay if this exact request was already handled, or
    IdempotencyConflict if the key is being reused with a different request body.
    Returns normally (does nothing) if this is a new key — the caller proceeds and
    must call `store_idempotency_result` before returning.

    Sets the RLS org context itself (like every other module/service function in
    this codebase) rather than assuming the caller already did — this function is
    commonly called in its own fresh transaction, after a prior one committed and
    reset the session-local `app.org_id` GUC.
    """
    set_org_context(db, org_id)
    # Serialize requests reusing the same key for the duration of the transaction.
    # This is deliberately a transaction-level advisory lock: it releases only when
    # the business mutation and its cached response are committed together.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"{org_id}:{key}"},
    )
    existing = db.scalar(
        select(IdempotencyKey).where(IdempotencyKey.org_id == org_id, IdempotencyKey.key == key)
    )
    if existing is None:
        return

    cutoff = datetime.now(existing.created_at.tzinfo) - timedelta(
        hours=get_settings().idempotency_key_ttl_hours
    )
    if existing.created_at <= cutoff:
        db.delete(existing)
        db.flush()
        return

    if existing.request_fingerprint != request_fp:
        raise IdempotencyConflict()
    raise IdempotencyReplay(existing.response_status, existing.response_body)


def store_idempotency_result(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
    request_fp: str,
    status: int,
    body: dict[str, Any],
) -> None:
    set_org_context(db, org_id)
    db.add(
        IdempotencyKey(
            id=uuid.uuid4(), org_id=org_id, user_id=user_id, key=key,
            request_fingerprint=request_fp, response_status=status, response_body=body,
        )
    )  # fmt: skip
