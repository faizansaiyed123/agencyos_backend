"""In-app notifications: a row per recipient plus a transactional `pg_notify` so live
subscribers (see app.modules.collab.stream) hear about it only if the change commits."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.models import Base, created_at_col, uuid_pk


def channel_for(org_id: uuid.UUID) -> str:
    return "org_" + org_id.hex  # identifier-safe: only hex digits


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_notifications_org_id_id"),
        ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_notifications_org_id_users",
            ondelete="CASCADE",
        ),
        Index("ix_notifications_org_id_user_id_read", "org_id", "user_id", "is_read", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_col()


def notify(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> Notification:
    n = Notification(
        org_id=org_id,
        user_id=user_id,
        kind=kind,
        title=title[:300],
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(n)
    db.flush()
    payload = f'{{"id":"{n.id}","user_id":"{user_id}","kind":"{kind}"}}'
    db.execute(text("SELECT pg_notify(:c, :p)"), {"c": channel_for(org_id), "p": payload})
    return n
