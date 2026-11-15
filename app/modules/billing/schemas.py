import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class InvoiceCreateRequest(BaseModel):
    client_id: uuid.UUID
    project_id: uuid.UUID | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    due_date: date | None = None
    tax_rate_bps: int = Field(default=0, ge=0, le=10000)
    notes: str | None = None


class InvoiceUpdateRequest(BaseModel):
    due_date: date | None = None
    tax_rate_bps: int | None = Field(default=None, ge=0, le=10000)
    notes: str | None = None


class LineCreateRequest(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    unit_cents: int = Field(ge=0)


class MilestoneLineRequest(BaseModel):
    milestone_id: uuid.UUID


class TimeLinesRequest(BaseModel):
    entry_ids: list[uuid.UUID] | None = None  # default: every approved, billable, unbilled entry


class PaymentRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    paid_on: date | None = None
    method: str = Field(default="bank_transfer", pattern="^(bank_transfer|card|cash|other)$")
    reference: str | None = Field(default=None, max_length=200)


class VoidRequest(BaseModel):
    reason: str = Field(min_length=3)


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    description: str
    quantity: Decimal
    unit_cents: int
    amount_cents: int
    position: int
    milestone_id: uuid.UUID | None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    amount_cents: int
    paid_on: date
    method: str
    reference: str | None
    created_at: datetime


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    project_id: uuid.UUID | None
    number: str | None
    status: str
    currency: str
    issue_date: date | None
    due_date: date | None
    tax_rate_bps: int
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    balance_cents: int = 0
    is_overdue: bool = False
    notes: str | None
    sent_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    created_at: datetime


class InvoiceDetailOut(BaseModel):
    invoice: InvoiceOut
    lines: list[LineOut]
    payments: list[PaymentOut]


class UnbilledRow(BaseModel):
    entry_id: uuid.UUID
    user_id: uuid.UUID
    entry_date: date
    minutes: int
    rate_cents: int | None
    amount_cents: int
