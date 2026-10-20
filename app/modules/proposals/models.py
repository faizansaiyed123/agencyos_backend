"""Proposals: priced scope sent to a client, linked to a deal. Line items are
only mutable while the proposal is a draft (app.modules.proposals.
proposal_states.is_editable) — once sent, the client may be looking at that
exact version.

Money: unit_amount is integer minor units (cents), never a float, matching
the money-handling rule used everywhere else in the system. quantity is
NUMERIC (not integer) because line items are sometimes priced by fractional
units (2.5 hours of consulting, for example).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, created_at_col, updated_at_col, uuid_pk
from app.modules.proposals.proposal_states import STATUSES

_STATUS_CHECK = "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")"


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_proposals_org_id_id"),  # target of composite FKs
        ForeignKeyConstraint(
            ["org_id", "client_id"], ["clients.org_id", "clients.id"],
            name="fk_proposals_org_id_clients", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "deal_id"], ["deals.org_id", "deals.id"],
            name="fk_proposals_org_id_deals", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "created_by"], ["users.org_id", "users.id"],
            name="fk_proposals_org_id_users", ondelete="RESTRICT",
        ),
        CheckConstraint(_STATUS_CHECK, name="status_valid"),
        CheckConstraint(
            "status != 'rejected' OR rejection_reason IS NOT NULL", name="rejected_requires_reason"
        ),
        Index("ix_proposals_org_id_status", "org_id", "status"),
        Index("ix_proposals_org_id_deal_id", "org_id", "deal_id"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    deal_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    valid_until: Mapped[date | None] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ProposalItem(Base):
    __tablename__ = "proposal_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "proposal_id"], ["proposals.org_id", "proposals.id"],
            name="fk_proposal_items_org_id_proposals", ondelete="CASCADE",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_amount >= 0", name="unit_amount_nonneg"),
        Index("ix_proposal_items_org_id_proposal_id", "org_id", "proposal_id"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    proposal_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    unit_amount: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
