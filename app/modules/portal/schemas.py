import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PortalClientOut(BaseModel):
    id: uuid.UUID
    name: str
    industry: str | None
    website: str | None


class PortalProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    status: str
    budget_amount: int | None
    currency: str
    start_date: date | None
    due_date: date | None


class PortalProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    currency: str
    valid_until: date | None
    sent_at: datetime | None
    accepted_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    total_amount: int


class PortalInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str | None
    status: str
    currency: str
    issue_date: date | None
    due_date: date | None
    total_cents: int
    amount_paid_cents: int
    balance_cents: int
    notes: str | None


class PortalOverviewOut(BaseModel):
    client: PortalClientOut
    projects: list[PortalProjectOut]
    proposals: list[PortalProposalOut]
    invoices: list[PortalInvoiceOut]


class PortalProposalItemOut(BaseModel):
    id: uuid.UUID
    description: str
    quantity: str
    unit_amount: int
    amount: int
    position: int


class PortalProposalDetailOut(BaseModel):
    proposal: PortalProposalOut
    items: list[PortalProposalItemOut]


class PortalRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
