"""CRM domain: clients, their contacts, and the deal pipeline.

Clients are soft-deleted (archived_at) — never hard-deleted — because deals,
and later invoices and projects, reference them; losing that history would
break reporting. Deals are never deleted at all: a lost deal is a terminal
pipeline stage, not an absence of a row, which is what makes win/loss
reporting possible at all.
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
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, created_at_col, updated_at_col, uuid_pk
from app.modules.crm.deal_states import STAGES

_STAGE_CHECK = "stage IN (" + ", ".join(f"'{s}'" for s in STAGES) + ")"


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_clients_org_id_id"),  # target of composite FKs
        ForeignKeyConstraint(
            ["org_id", "created_by"], ["users.org_id", "users.id"],
            name="fk_clients_org_id_users", ondelete="RESTRICT",
        ),
        Index("ix_clients_org_id_archived_at", "org_id", "archived_at"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Contact(Base):
    """A person at a client. Hard-deletable (unlike Client/Deal) — a contact
    leaving the client company isn't business history worth preserving the
    way a lost deal or an archived client relationship is; the audit log
    still records the deletion event itself if that's ever needed."""

    __tablename__ = "contacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "client_id"], ["clients.org_id", "clients.id"],
            name="fk_contacts_org_id_clients", ondelete="CASCADE",
        ),
        Index("ix_contacts_org_id_client_id", "org_id", "client_id"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(150))
    is_primary: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Deal(Base):
    """An opportunity moving through the pipeline. `value_amount` is integer
    minor units (cents) — never a float — matching the money-handling rule
    for the whole system (see billing, when it's built). Stage transitions
    are validated by app.modules.crm.deal_states and additionally constrained
    here at the database level as a second, independent layer."""

    __tablename__ = "deals"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_deals_org_id_id"),  # target of composite FKs
        ForeignKeyConstraint(
            ["org_id", "client_id"], ["clients.org_id", "clients.id"],
            name="fk_deals_org_id_clients", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "owner_user_id"], ["users.org_id", "users.id"],
            name="fk_deals_org_id_users", ondelete="RESTRICT",
        ),
        CheckConstraint(_STAGE_CHECK, name="stage_valid"),
        CheckConstraint("value_amount IS NULL OR value_amount >= 0", name="value_amount_nonneg"),
        # A deal can only be won with a positive value on file — you can't
        # report pipeline revenue on a deal nobody ever priced.
        CheckConstraint(
            "stage != 'won' OR (value_amount IS NOT NULL AND value_amount > 0)",
            name="won_requires_value",
        ),
        # A lost deal must record why, or loss-reason reporting is meaningless.
        CheckConstraint(
            "stage != 'lost' OR lost_reason IS NOT NULL", name="lost_requires_reason"
        ),
        Index("ix_deals_org_id_stage", "org_id", "stage"),
        Index("ix_deals_org_id_client_id", "org_id", "client_id"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(20), default="lead")
    value_amount: Mapped[int | None] = mapped_column(BigInteger)
    value_currency: Mapped[str] = mapped_column(String(3), default="USD")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class DealStageHistory(Base):
    """Append-only log of every stage transition — the same
    write-in-the-same-transaction-as-the-change pattern as audit_log, but
    scoped to one deal so pipeline-velocity reporting can query it directly
    without filtering the global audit log."""

    __tablename__ = "deal_stage_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "deal_id"], ["deals.org_id", "deals.id"],
            name="fk_deal_stage_history_org_id_deals", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "changed_by"], ["users.org_id", "users.id"],
            name="fk_deal_stage_history_org_id_users", ondelete="RESTRICT",
        ),
        Index("ix_deal_stage_history_org_id_deal_id", "org_id", "deal_id"),
    )  # fmt: skip

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    deal_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    from_stage: Mapped[str | None] = mapped_column(String(20))
    to_stage: Mapped[str] = mapped_column(String(20))
    changed_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
