"""Collaboration: comments (on any entity), approval requests, in-app notifications.

Comments and approvals point at an (entity_type, entity_id) pair. Because the target
can be any table, there is deliberately no FK to it; the service validates that the
target exists in the caller's org before writing, and RLS scopes every row.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, created_at_col, updated_at_col, uuid_pk

ENTITY_TYPES = ("project", "task", "client", "deal", "proposal", "invoice")


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "author_id"],
            ["users.org_id", "users.id"],
            name="fk_comments_org_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint("char_length(body) BETWEEN 1 AND 5000", name="body_length"),
        Index("ix_comments_org_id_entity", "org_id", "entity_type", "entity_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class ApprovalRequest(Base):
    """'Please approve X' — e.g. a deliverable, a proposal or an invoice before it goes
    out. One decision, final; the requester cannot decide their own request."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "requested_by"],
            ["users.org_id", "users.id"],
            name="fk_approval_requests_org_id_requesters",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "approver_id"],
            ["users.org_id", "users.id"],
            name="fk_approval_requests_org_id_approvers",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')", name="status_valid"
        ),
        CheckConstraint("requested_by != approver_id", name="no_self_approval"),
        CheckConstraint(
            "status != 'rejected' OR decision_note IS NOT NULL", name="rejection_needs_note"
        ),
        Index("ix_approval_requests_org_id_approver", "org_id", "approver_id", "status"),
        Index("ix_approval_requests_org_id_entity", "org_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(300))
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    approver_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
