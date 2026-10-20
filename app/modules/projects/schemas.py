"""Pydantic models for the projects module."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.projects.project_states import STATUSES, TASK_PRIORITIES, TASK_STATUSES


def _one_of(v: str | None, allowed: tuple[str, ...]) -> str | None:
    if v is not None and v not in allowed:
        raise ValueError(f"must be one of {allowed}")
    return v


class ProjectCreateRequest(BaseModel):
    client_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    budget_amount: int | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    start_date: date | None = None
    due_date: date | None = None
    manager_user_id: uuid.UUID | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    budget_amount: int | None = Field(default=None, ge=0)
    start_date: date | None = None
    due_date: date | None = None
    manager_user_id: uuid.UUID | None = None


class ProjectStatusRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _v(cls, v: str) -> str:
        return _one_of(v, STATUSES) or v


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    deal_id: uuid.UUID | None
    proposal_id: uuid.UUID | None
    name: str
    description: str | None
    status: str
    budget_amount: int | None
    currency: str
    start_date: date | None
    due_date: date | None
    manager_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MemberAddRequest(BaseModel):
    user_id: uuid.UUID
    hourly_rate_cents: int | None = Field(default=None, ge=0)


class MemberUpdateRequest(BaseModel):
    hourly_rate_cents: int | None = Field(default=None, ge=0)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    user_id: uuid.UUID
    hourly_rate_cents: int | None


class MilestoneCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    due_date: date | None = None
    amount_cents: int | None = Field(default=None, ge=0)
    position: int = 0


class MilestoneUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: date | None = None
    amount_cents: int | None = Field(default=None, ge=0)
    position: int | None = None
    done: bool | None = None


class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    due_date: date | None
    amount_cents: int | None
    status: str
    position: int
    completed_at: datetime | None


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    milestone_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID | None = None
    priority: str = "medium"
    due_date: date | None = None
    estimate_minutes: int | None = Field(default=None, ge=0)

    @field_validator("priority")
    @classmethod
    def _p(cls, v: str) -> str:
        return _one_of(v, TASK_PRIORITIES) or v


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    milestone_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID | None = None
    unassign: bool = False
    status: str | None = None
    priority: str | None = None
    due_date: date | None = None
    estimate_minutes: int | None = Field(default=None, ge=0)

    @field_validator("status")
    @classmethod
    def _s(cls, v: str | None) -> str | None:
        return _one_of(v, TASK_STATUSES)

    @field_validator("priority")
    @classmethod
    def _p(cls, v: str | None) -> str | None:
        return _one_of(v, TASK_PRIORITIES)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    milestone_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    priority: str
    assignee_user_id: uuid.UUID | None
    due_date: date | None
    estimate_minutes: int | None
    completed_at: datetime | None
    created_at: datetime


class ProjectDetailOut(BaseModel):
    project: ProjectOut
    members: list[MemberOut]
    milestones: list[MilestoneOut]
    task_counts: dict[str, int]
