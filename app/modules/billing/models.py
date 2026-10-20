"""Billing: invoices, lines, payments and the per-year gapless number counter.

Money is integer cents everywhere; tax is integer basis points (1900 = 19%).
Invoice numbers are assigned when an invoice is ISSUED, not when drafted, so
discarding drafts never leaves gaps. The counter row is locked by the UPDATE inside
the issuing transaction, which serialises concurrent issuers and rolls the increment
back with the transaction if anything fails — numbers are gapless and unique.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, created_at_col, updated_at_col, uuid_pk
from app.modules.billing.invoice_states import STATUSES


class InvoiceCounter(Base):
    __tablename__ = "invoice_counters"
    __table_args__ = (PrimaryKeyConstraint("org_id", "year", name="pk_invoice_counters"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    year: Mapped[int] = mapped_column(Integer)
    last_number: Mapped[int] = mapped_column(Integer, default=0)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_invoices_org_id_id"),
        UniqueConstraint("org_id", "number", name="uq_invoices_org_id_number"),
        ForeignKeyConstraint(
            ["org_id", "client_id"],
            ["clients.org_id", "clients.id"],
            name="fk_invoices_org_id_clients",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_invoices_org_id_projects",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "created_by"],
            ["users.org_id", "users.id"],
            name="fk_invoices_org_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")", name="status_valid"
        ),
        CheckConstraint("status = 'draft' OR number IS NOT NULL", name="issued_has_number"),
        CheckConstraint("tax_rate_bps >= 0 AND tax_rate_bps <= 10000", name="tax_rate_range"),
        CheckConstraint("subtotal_cents >= 0 AND tax_cents >= 0", name="amounts_nonneg"),
        CheckConstraint("total_cents = subtotal_cents + tax_cents", name="total_consistent"),
        CheckConstraint(
            "amount_paid_cents >= 0 AND amount_paid_cents <= total_cents", name="paid_within_total"
        ),
        CheckConstraint(
            "status != 'paid' OR amount_paid_cents = total_cents", name="paid_means_settled"
        ),
        CheckConstraint("status != 'void' OR void_reason IS NOT NULL", name="void_requires_reason"),
        Index("ix_invoices_org_id_status", "org_id", "status"),
        Index("ix_invoices_org_id_client_id", "org_id", "client_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    number: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(15), default="draft")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    tax_rate_bps: Mapped[int] = mapped_column(Integer, default=0)
    subtotal_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    amount_paid_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "invoice_id"],
            ["invoices.org_id", "invoices.id"],
            name="fk_invoice_lines_org_id_invoices",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "milestone_id"],
            ["milestones.org_id", "milestones.id"],
            name="fk_invoice_lines_org_id_milestones",
            ondelete="SET NULL (milestone_id)",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cents >= 0 AND amount_cents >= 0", name="amounts_nonneg"),
        Index("ix_invoice_lines_org_id_invoice_id", "org_id", "invoice_id"),
        Index("ix_invoice_lines_org_id_milestone_id", "org_id", "milestone_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    unit_cents: Mapped[int] = mapped_column(BigInteger)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(Integer, default=0)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    time_entry_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Payment(Base):
    """Immutable once recorded — payments are corrected by voiding the invoice
    (when unpaid) or by an accounting adjustment outside this system, never edited."""

    __tablename__ = "payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "invoice_id"],
            ["invoices.org_id", "invoices.id"],
            name="fk_payments_org_id_invoices",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "created_by"],
            ["users.org_id", "users.id"],
            name="fk_payments_org_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint(
            "method IN ('bank_transfer', 'card', 'cash', 'other')", name="method_valid"
        ),
        Index("ix_payments_org_id_invoice_id", "org_id", "invoice_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    paid_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(20), default="bank_transfer")
    reference: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
