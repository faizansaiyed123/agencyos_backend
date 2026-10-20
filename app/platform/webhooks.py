"""Outbound webhooks: signed, retried, tenant-scoped.

Flow: a service calls `events.emit()` inside its transaction -> `fan_out()` writes
one `webhook_deliveries` row per subscribed endpoint and enqueues a delivery job
in the SAME transaction (transactional outbox). The worker signs and POSTs the
payload; any non-2xx/exception raises so the job queue's exponential backoff
retries it, and after max attempts it lands in dead_letter.

Signature header: `X-AgencyOS-Signature: t=<unix>,v1=<hex hmac-sha256(secret, f"{t}.{body}")>`.
Receivers should reject timestamps older than a few minutes (replay protection).

SSRF: endpoints must be https (http only outside prod), may not be IP literals in
private ranges or `localhost`, and the real sender additionally resolves DNS and
refuses private/loopback/link-local answers right before connecting.
"""

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.db import set_org_context
from app.core.errors import BusinessRuleViolation
from app.core.models import Base, created_at_col, uuid_pk
from app.platform import jobs

EVENT_TYPES = (
    "project.created",
    "project.active",
    "project.on_hold",
    "project.completed",
    "project.cancelled",
    "milestone.completed",
    "task.assigned",
    "task.completed",
    "invoice.created",
    "invoice.sent",
    "invoice.paid",
    "invoice.voided",
    "payment.recorded",
    "approval.requested",
    "approval.decided",
    "time.approved",
)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_webhook_endpoints_org_id_id"),
        ForeignKeyConstraint(
            ["org_id", "created_by"],
            ["users.org_id", "users.id"],
            name="fk_webhook_endpoints_org_id_users",
            ondelete="RESTRICT",
        ),
        Index("ix_webhook_endpoints_org_id", "org_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    url: Mapped[str] = mapped_column(String(2000))
    secret_encrypted: Mapped[str] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(ARRAY(String(60)))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "endpoint_id"],
            ["webhook_endpoints.org_id", "webhook_endpoints.id"],
            name="fk_webhook_deliveries_org_id_webhook_endpoints",
            ondelete="CASCADE",
        ),
        Index("ix_webhook_deliveries_org_id_endpoint_id", "org_id", "endpoint_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|success|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def generate_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def validate_endpoint_url(url: str) -> None:
    parsed = urlparse(url)
    prod = get_settings().env == "prod"
    if parsed.scheme not in ("https", "http") or (prod and parsed.scheme != "https"):
        raise BusinessRuleViolation("Webhook URL must use https", code="invalid_webhook_url")
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        raise BusinessRuleViolation("Webhook URL host is not allowed", code="invalid_webhook_url")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if not ip.is_global:
        raise BusinessRuleViolation(
            "Webhook URL may not target a private address", code="invalid_webhook_url"
        )


def sign(secret: str, timestamp: int, body: str) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify_signature(secret: str, header: str, body: str, *, tolerance_seconds: int = 300) -> bool:
    """Reference verifier for receivers (also used by tests)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(time.time() - ts) > tolerance_seconds:
        return False
    return hmac.compare_digest(sign(secret, ts, body), header)


def fan_out(db: Session, *, org_id: uuid.UUID, event_type: str, data: dict[str, Any]) -> None:
    set_org_context(db, org_id)
    endpoints = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.org_id == org_id, WebhookEndpoint.is_active.is_(True)
        )
    ).all()
    for ep in endpoints:
        if "*" not in ep.events and event_type not in ep.events:
            continue
        delivery = WebhookDelivery(
            org_id=org_id,
            endpoint_id=ep.id,
            event_type=event_type,
            payload={"type": event_type, "created_at": utcnow().isoformat(), "data": data},
        )
        db.add(delivery)
        db.flush()
        jobs.enqueue(
            db,
            job_type="deliver_webhook",
            org_id=org_id,
            payload={"org_id": str(org_id), "delivery_id": str(delivery.id)},
        )


Sender = Callable[[str, dict[str, str], str], int]


def _real_sender(url: str, headers: dict[str, str], body: str) -> int:
    host = urlparse(url).hostname or ""
    if get_settings().env == "prod":
        for info in socket.getaddrinfo(host, None):
            if not ipaddress.ip_address(info[4][0]).is_global:
                raise RuntimeError("endpoint resolves to a non-public address")
    resp = httpx.post(url, content=body, headers=headers, timeout=10.0, follow_redirects=False)
    return resp.status_code


_sender: Sender = _real_sender


def set_sender(sender: Sender | None) -> None:
    """Test seam: swap the HTTP transport."""
    global _sender  # noqa: PLW0603
    _sender = sender or _real_sender


def _deliver(payload: dict[str, Any], db: Session) -> None:
    org_id = uuid.UUID(payload["org_id"])
    set_org_context(db, org_id)
    delivery = db.get(WebhookDelivery, uuid.UUID(payload["delivery_id"]))
    if delivery is None or delivery.status == "success":
        return
    endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
    if endpoint is None or not endpoint.is_active:
        delivery.status = "failed"
        delivery.last_error = "endpoint disabled or deleted"
        db.commit()
        return
    body = json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True)
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "X-AgencyOS-Event": delivery.event_type,
        "X-AgencyOS-Delivery": str(delivery.id),
        "X-AgencyOS-Signature": sign(decrypt_secret(endpoint.secret_encrypted), ts, body),
    }
    delivery.attempts += 1
    try:
        status = _sender(endpoint.url, headers, body)
        delivery.response_status = status
        if not 200 <= status < 300:
            raise RuntimeError(f"endpoint responded {status}")
    except Exception as exc:
        delivery.status = "pending"
        delivery.last_error = str(exc)[:500]
        db.commit()
        raise  # the job queue schedules the retry with backoff
    delivery.status = "success"
    delivery.last_error = None
    delivery.delivered_at = utcnow()
    db.commit()


def register() -> None:
    jobs.register_handler("deliver_webhook", _deliver)


__all__ = [
    "EVENT_TYPES",
    "decrypt_secret",
    "encrypt_secret",
    "fan_out",
    "generate_secret",
    "register",
    "sign",
    "verify_signature",
]
