"""Feature flags: per-organisation switch plus an optional percentage rollout.

A flag is ON for a user when the org row is enabled AND the user falls inside the
rollout bucket. The bucket is a stable hash of (flag, user), so a user never flips
back and forth between requests, and raising the percentage only ever adds users."""

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    Uuid,
    func,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import set_org_context
from app.core.errors import NotFound
from app.core.models import Base

# key -> (description, default enabled when no row exists)
REGISTRY: dict[str, tuple[str, bool]] = {
    "assistant": ("Keyword search assistant", True),
    "new_dashboard": ("Redesigned overview dashboard", False),
    "client_portal": ("Client-facing portal (preview)", False),
    "beta_reports": ("Experimental reports", False),
}


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    __table_args__ = (
        PrimaryKeyConstraint("org_id", "key", name="pk_feature_flags"),
        ForeignKeyConstraint(
            ["org_id", "updated_by"],
            ["users.org_id", "users.id"],
            name="fk_feature_flags_org_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint("rollout_percent BETWEEN 0 AND 100", name="rollout_range"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rollout_percent: Mapped[int] = mapped_column(Integer, default=100)
    updated_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def bucket(key: str, user_id: uuid.UUID) -> int:
    digest = hashlib.sha256(f"{key}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100


def _row(db: Session, org_id: uuid.UUID, key: str) -> FeatureFlag | None:
    return db.scalar(
        select(FeatureFlag).where(FeatureFlag.org_id == org_id, FeatureFlag.key == key)
    )


def is_enabled(db: Session, org_id: uuid.UUID, user_id: uuid.UUID, key: str) -> bool:
    if key not in REGISTRY:
        raise NotFound(f"Unknown feature flag '{key}'")
    set_org_context(db, org_id)
    row = _row(db, org_id, key)
    if row is None:
        return REGISTRY[key][1]
    return row.enabled and bucket(key, user_id) < row.rollout_percent


def evaluate_all(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, bool]:
    return {k: is_enabled(db, org_id, user_id, k) for k in REGISTRY}


def set_flag(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    key: str,
    enabled: bool,
    rollout_percent: int,
) -> FeatureFlag:
    if key not in REGISTRY:
        raise NotFound(f"Unknown feature flag '{key}'")
    set_org_context(db, org_id)
    row = _row(db, org_id, key)
    if row is None:
        row = FeatureFlag(
            org_id=org_id,
            key=key,
            enabled=enabled,
            rollout_percent=rollout_percent,
            updated_by=actor_id,
        )
        db.add(row)
    else:
        row.enabled, row.rollout_percent, row.updated_by = enabled, rollout_percent, actor_id
    db.flush()
    return row


def list_flags(db: Session, org_id: uuid.UUID) -> dict[str, FeatureFlag]:
    set_org_context(db, org_id)
    return {r.key: r for r in db.scalars(select(FeatureFlag).where(FeatureFlag.org_id == org_id))}
