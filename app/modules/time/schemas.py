import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class TimerStartRequest(BaseModel):
    project_id: uuid.UUID
    task_id: uuid.UUID | None = None
    description: str | None = None
    billable: bool = True


class ManualEntryRequest(BaseModel):
    project_id: uuid.UUID
    task_id: uuid.UUID | None = None
    description: str | None = None
    entry_date: date
    minutes: int = Field(ge=1, le=1440)
    billable: bool = True


class EntryUpdateRequest(BaseModel):
    description: str | None = None
    entry_date: date | None = None
    minutes: int | None = Field(default=None, ge=1, le=1440)
    billable: bool | None = None
    task_id: uuid.UUID | None = None


class ApproveRequest(BaseModel):
    entry_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID | None
    description: str | None
    entry_date: date
    started_at: datetime
    ended_at: datetime | None
    minutes: int
    billable: bool
    rate_cents: int | None
    status: str
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    invoice_id: uuid.UUID | None


class SummaryRow(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    minutes: int
    billable_minutes: int
    amount_cents: int
