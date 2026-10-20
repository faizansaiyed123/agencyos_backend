"""Pydantic request/response models for the CRM module."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.crm.deal_states import STAGES


class ClientCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class ClientUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    industry: str | None
    website: str | None
    notes: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContactCreateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=150)
    is_primary: bool = False


class ContactUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=150)
    is_primary: bool | None = None


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    title: str | None
    is_primary: bool
    created_at: datetime


class DealCreateRequest(BaseModel):
    client_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    value_amount: int | None = Field(default=None, ge=0)
    value_currency: str = Field(default="USD", min_length=3, max_length=3)
    owner_user_id: uuid.UUID | None = None
    expected_close_date: date | None = None


class DealUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    value_amount: int | None = Field(default=None, ge=0)
    value_currency: str | None = Field(default=None, min_length=3, max_length=3)
    owner_user_id: uuid.UUID | None = None
    expected_close_date: date | None = None


class DealStageChangeRequest(BaseModel):
    to_stage: str
    lost_reason: str | None = None
    note: str | None = None

    @field_validator("to_stage")
    @classmethod
    def _valid_stage(cls, v: str) -> str:
        if v not in STAGES:
            raise ValueError(f"to_stage must be one of {STAGES}")
        return v


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    title: str
    description: str | None
    stage: str
    value_amount: int | None
    value_currency: str
    owner_user_id: uuid.UUID
    expected_close_date: date | None
    closed_at: datetime | None
    lost_reason: str | None
    created_at: datetime
    updated_at: datetime


class DealStageHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_stage: str | None
    to_stage: str
    changed_by: uuid.UUID
    note: str | None
    created_at: datetime
