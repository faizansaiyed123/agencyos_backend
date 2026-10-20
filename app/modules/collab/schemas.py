import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CommentCreate(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    body: str = Field(min_length=1, max_length=5000)


class CommentEdit(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    author_id: uuid.UUID
    body: str
    mentions: list[str]
    edited_at: datetime | None
    created_at: datetime


class ApprovalCreate(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    approver_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)


class ApprovalDecision(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=2000)


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    title: str
    requested_by: uuid.UUID
    approver_id: uuid.UUID
    status: str
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    is_read: bool
    created_at: datetime


class MarkReadRequest(BaseModel):
    ids: list[uuid.UUID] | None = None  # omit to mark everything read


class StreamTicket(BaseModel):
    ticket: str
    expires_in: int
