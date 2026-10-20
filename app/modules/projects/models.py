"""Projects domain: projects, team membership, milestones and tasks.

A project is created either by hand or — the main path — when a proposal is
accepted (see proposals.service.accept_proposal). `deal_id` is unique per org
so conversion is idempotent. Money is integer cents.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, created_at_col, updated_at_col, uuid_pk
from app.modules.projects.project_states import STATUSES, TASK_PRIORITIES, TASK_STATUSES


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_projects_org_id_id"),
        ForeignKeyConstraint(
            ["org_id", "client_id"],
            ["clients.org_id", "clients.id"],
            name="fk_projects_org_id_clients",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "deal_id"],
            ["deals.org_id", "deals.id"],
            name="fk_projects_org_id_deals",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "manager_user_id"],
            ["users.org_id", "users.id"],
            name="fk_projects_org_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in("status", STATUSES), name="status_valid"),
        CheckConstraint("budget_amount IS NULL OR budget_amount >= 0", name="budget_nonneg"),
        Index("ix_projects_org_id_status", "org_id", "status"),
        Index("ix_projects_org_id_client_id", "org_id", "client_id"),
        # One project per deal: makes proposal->project conversion idempotent.
        Index(
            "uq_projects_one_per_deal",
            "org_id",
            "deal_id",
            unique=True,
            postgresql_where="deal_id IS NOT NULL",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="planning")
    budget_amount: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    manager_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ProjectMember(Base):
    """Team assignment. `hourly_rate_cents` is the billing rate; time entries
    snapshot it when logged so later rate changes never rewrite history."""

    __tablename__ = "project_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_project_members_org_id_projects",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_project_members_org_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint("hourly_rate_cents IS NULL OR hourly_rate_cents >= 0", name="rate_nonneg"),
        Index("ix_project_members_org_id_user_id", "org_id", "user_id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    hourly_rate_cents: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at_col()


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_milestones_org_id_id"),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_milestones_org_id_projects",
            ondelete="CASCADE",
        ),
        CheckConstraint("amount_cents IS NULL OR amount_cents >= 0", name="amount_nonneg"),
        CheckConstraint("status IN ('pending', 'done')", name="status_valid"),
        Index("ix_milestones_org_id_project_id", "org_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(Date)
    amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    position: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_tasks_org_id_id"),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_tasks_org_id_projects",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "milestone_id"],
            ["milestones.org_id", "milestones.id"],
            name="fk_tasks_org_id_milestones",
            ondelete="SET NULL (milestone_id)",
        ),
        ForeignKeyConstraint(
            ["org_id", "assignee_user_id"],
            ["users.org_id", "users.id"],
            name="fk_tasks_org_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in("status", TASK_STATUSES), name="status_valid"),
        CheckConstraint(_in("priority", TASK_PRIORITIES), name="priority_valid"),
        CheckConstraint(
            "estimate_minutes IS NULL OR estimate_minutes >= 0", name="estimate_nonneg"
        ),
        Index("ix_tasks_org_id_project_id", "org_id", "project_id"),
        Index("ix_tasks_org_id_assignee", "org_id", "assignee_user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="todo")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    due_date: Mapped[date | None] = mapped_column(Date)
    estimate_minutes: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
