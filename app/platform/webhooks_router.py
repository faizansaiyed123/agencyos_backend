"""Admin API for webhook endpoints and delivery history."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_secret
from app.core.db import get_db, set_org_context
from app.core.errors import NotFound
from app.core.permissions import Perm
from app.modules.identity.deps import require
from app.modules.identity.models import User
from app.platform.audit import record_audit
from app.platform.webhooks import (
    EVENT_TYPES,
    WebhookDelivery,
    WebhookEndpoint,
    generate_secret,
    validate_endpoint_url,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require(Perm.WEBHOOK_MANAGE))]


class EndpointIn(BaseModel):
    url: str = Field(max_length=2000)
    events: list[str] = Field(min_length=1)

    @field_validator("events")
    @classmethod
    def _events(cls, v: list[str]) -> list[str]:
        bad = [e for e in v if e != "*" and e not in EVENT_TYPES]
        if bad:
            raise ValueError(f"unknown event types: {bad}")
        return v


class EndpointPatch(BaseModel):
    events: list[str] | None = None
    is_active: bool | None = None


class EndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime
    secret: str | None = None  # present only in the create response


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    response_status: int | None
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None


@router.get("/event-types", response_model=list[str])
def event_types(_: Admin) -> list[str]:
    return list(EVENT_TYPES)


@router.post("", response_model=EndpointOut, status_code=201)
def create_endpoint(body: EndpointIn, user: Admin, db: Db) -> EndpointOut:
    validate_endpoint_url(body.url)
    set_org_context(db, user.org_id)
    secret = generate_secret()
    ep = WebhookEndpoint(
        org_id=user.org_id,
        url=body.url,
        events=body.events,
        secret_encrypted=encrypt_secret(secret),
        created_by=user.id,
    )
    db.add(ep)
    db.flush()
    record_audit(
        db,
        org_id=user.org_id,
        actor_user_id=user.id,
        action="webhook.created",
        entity_type="webhook_endpoint",
        entity_id=ep.id,
        data={"url": body.url},
    )
    db.commit()
    out = EndpointOut.model_validate(ep)
    out.secret = secret
    return out


@router.get("", response_model=list[EndpointOut])
def list_endpoints(user: Admin, db: Db) -> list[EndpointOut]:
    set_org_context(db, user.org_id)
    rows = db.scalars(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.org_id == user.org_id)
        .order_by(WebhookEndpoint.created_at)
    )
    return [EndpointOut.model_validate(r) for r in rows]


def _get(db: Session, org_id: uuid.UUID, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    set_org_context(db, org_id)
    ep = db.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.org_id == org_id, WebhookEndpoint.id == endpoint_id
        )
    )
    if ep is None:
        raise NotFound("Webhook endpoint not found")
    return ep


@router.patch("/{endpoint_id}", response_model=EndpointOut)
def patch_endpoint(endpoint_id: uuid.UUID, body: EndpointPatch, user: Admin, db: Db) -> EndpointOut:
    ep = _get(db, user.org_id, endpoint_id)
    if body.events is not None:
        EndpointIn(url=ep.url, events=body.events)  # reuse validation
        ep.events = body.events
    if body.is_active is not None:
        ep.is_active = body.is_active
    record_audit(
        db,
        org_id=user.org_id,
        actor_user_id=user.id,
        action="webhook.updated",
        entity_type="webhook_endpoint",
        entity_id=ep.id,
    )
    db.commit()
    return EndpointOut.model_validate(ep)


@router.delete("/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: uuid.UUID, user: Admin, db: Db) -> None:
    ep = _get(db, user.org_id, endpoint_id)
    db.delete(ep)
    record_audit(
        db,
        org_id=user.org_id,
        actor_user_id=user.id,
        action="webhook.deleted",
        entity_type="webhook_endpoint",
        entity_id=ep.id,
    )
    db.commit()


@router.get("/{endpoint_id}/deliveries", response_model=list[DeliveryOut])
def deliveries(endpoint_id: uuid.UUID, user: Admin, db: Db) -> list[DeliveryOut]:
    _get(db, user.org_id, endpoint_id)
    rows = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.org_id == user.org_id, WebhookDelivery.endpoint_id == endpoint_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(50)
    )
    return [DeliveryOut.model_validate(r) for r in rows]
