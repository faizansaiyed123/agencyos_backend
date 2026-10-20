"""Server-Sent Events over Postgres LISTEN/NOTIFY.

Browsers' EventSource cannot send an Authorization header, so the client first
POSTs for a 60-second, purpose-bound ticket (a signed JWT) and opens the stream
with it. The ticket is useless for any other API call.
"""

import json
import time
import uuid
from collections.abc import Iterator
from datetime import timedelta

import jwt
import psycopg

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.core.security import JWT_ALGORITHM
from app.platform.notifications import channel_for

TICKET_TTL_SECONDS = 60
_PURPOSE = "notifications-stream"


def issue_ticket(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    claims = {
        "sub": str(user_id),
        "org": str(org_id),
        "typ": "stream",
        "purpose": _PURPOSE,
        "exp": utcnow() + timedelta(seconds=TICKET_TTL_SECONDS),
    }
    return jwt.encode(claims, get_settings().jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def verify_ticket(ticket: str) -> tuple[uuid.UUID, uuid.UUID]:
    try:
        claims = jwt.decode(
            ticket, get_settings().jwt_secret.get_secret_value(), algorithms=[JWT_ALGORITHM]
        )
        if claims.get("purpose") != _PURPOSE or claims.get("typ") != "stream":
            raise Unauthorized("Invalid stream ticket")
        return uuid.UUID(claims["sub"]), uuid.UUID(claims["org"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise Unauthorized("Invalid or expired stream ticket") from exc


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


def event_stream(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    keepalive_seconds: float = 15.0,
    max_events: int | None = None,
    deadline_seconds: float = 3600.0,
) -> Iterator[str]:
    """Yields SSE frames for this user's notifications until the deadline (clients
    reconnect) or `max_events` (used by tests). Opens one dedicated connection."""
    end = time.monotonic() + deadline_seconds
    sent = 0
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        conn.execute(f"LISTEN {channel_for(org_id)}")  # noqa: S608 — channel is 'org_' + hex only
        yield "retry: 3000\n\n"
        while time.monotonic() < end:
            got = False
            for note in conn.notifies(timeout=keepalive_seconds, stop_after=1):
                got = True
                try:
                    data = json.loads(note.payload)
                except ValueError:
                    continue
                if data.get("user_id") != str(user_id):
                    continue  # other users' notifications in the same org are never sent
                yield f"event: notification\ndata: {json.dumps(data)}\n\n"
                sent += 1
                if max_events is not None and sent >= max_events:
                    return
            if not got:
                yield ": keepalive\n\n"
