"""Append-only audit trail, written in the same transaction as the change it records.

The runtime DB role is granted INSERT and SELECT only on audit_log, so history cannot
be rewritten even by a bug or an injection in the application.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKeyConstraint, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.models import Base, created_at_col


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "actor_user_id"], ["users.org_id", "users.id"], ondelete="RESTRICT",
            name="fk_audit_log_org_id_users",
        ),
        Index("ix_audit_log_org_id_created_at", "org_id", "created_at"),
        Index("ix_audit_log_entity", "org_id", "entity_type", "entity_id"),
    )  # fmt: skip

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = created_at_col()


def record_audit(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            data=data or {},
        )
    )
