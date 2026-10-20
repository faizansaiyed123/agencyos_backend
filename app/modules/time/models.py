"""Time tracking. An entry with `ended_at IS NULL` is a running timer; a partial
unique index allows at most one per user. `rate_cents` snapshots the member's hourly
rate when the entry is created, so later rate changes never rewrite history.

Lifecycle: draft -> approved -> invoiced (billing sets invoiced). Approved and
invoiced entries are immutable.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, created_at_col, updated_at_col, uuid_pk


class TimeEntry(Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_time_entries_org_id_users",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "approved_by"],
            ["users.org_id", "users.id"],
            name="fk_time_entries_org_id_approvers",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_time_entries_org_id_projects",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "task_id"],
            ["tasks.org_id", "tasks.id"],
            name="fk_time_entries_org_id_tasks",
            ondelete="SET NULL (task_id)",
        ),
        ForeignKeyConstraint(
            ["org_id", "invoice_id"],
            ["invoices.org_id", "invoices.id"],
            name="fk_time_entries_org_id_invoices",
            ondelete="SET NULL (invoice_id)",
        ),
        CheckConstraint("status IN ('draft', 'approved', 'invoiced')", name="status_valid"),
        CheckConstraint(
            "status != 'invoiced' OR invoice_id IS NOT NULL", name="invoiced_has_invoice"
        ),
        CheckConstraint("minutes >= 0 AND minutes <= 1440", name="minutes_range"),
        CheckConstraint("rate_cents IS NULL OR rate_cents >= 0", name="rate_nonneg"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ends_after_start"),
        Index("ix_time_entries_org_id_user_id_date", "org_id", "user_id", "entry_date"),
        Index("ix_time_entries_org_id_project_id", "org_id", "project_id", "status"),
        Index(
            "uq_time_entries_one_running_timer_per_user",
            "org_id",
            "user_id",
            unique=True,
            postgresql_where="ended_at IS NULL",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    description: Mapped[str | None] = mapped_column(Text)
    entry_date: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_cents: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), default="draft")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


def amount_cents(minutes: int, rate_cents: int | None) -> int:
    """Billable amount in cents, rounded half-up, integer arithmetic only."""
    if not rate_cents:
        return 0
    return (minutes * rate_cents + 30) // 60
