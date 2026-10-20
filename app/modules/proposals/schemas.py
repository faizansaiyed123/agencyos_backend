"""Pydantic request/response models for the proposals module."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProposalCreateRequest(BaseModel):
    client_id: uuid.UUID
    deal_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    valid_until: date | None = None


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    deal_id: uuid.UUID
    title: str
    status: str
    currency: str
    valid_until: date | None
    sent_at: datetime | None
    accepted_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class ProposalItemCreateRequest(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, decimal_places=2)
    unit_amount: int = Field(ge=0)
    position: int = 0


class ProposalItemUpdateRequest(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    quantity: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    unit_amount: int | None = Field(default=None, ge=0)
    position: int | None = None


class ProposalItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    proposal_id: uuid.UUID
    description: str
    quantity: Decimal
    unit_amount: int
    position: int


class ProposalRejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class ProposalWithItemsOut(BaseModel):
    proposal: ProposalOut
    items: list[ProposalItemOut]
    total_amount: int
