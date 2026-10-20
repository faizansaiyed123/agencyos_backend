"""Sliding-window rate limiting, atomic in Postgres — no Redis.

The actual counting happens in a single SQL statement (the `rate_limit_hit`
function, created in the migration): an UPSERT whose SET clause resets the
window when it's expired and increments it otherwise. Because it's one
statement, Postgres's row-level lock during the UPSERT makes it safe under
concurrent requests for the same key — there's no read-then-write race.

This table is NOT tenant-scoped and has no RLS: it's used before a caller's org
is known (login/signup, keyed by IP or email) and holds no tenant data, only
opaque counters.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    title = "Too many requests — please try again later"


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_at: datetime


def check_rate_limit(db: Session, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
    row = db.execute(
        text("SELECT * FROM rate_limit_hit(:key, :limit, :window)"),
        {"key": key, "limit": limit, "window": window_seconds},
    ).one()
    return RateLimitResult(allowed=row.allowed, remaining=row.remaining, reset_at=row.reset_at)


def enforce_rate_limit(db: Session, *, key: str, limit: int, window_seconds: int) -> None:
    """Convenience wrapper: raises RateLimited (429) instead of returning a result
    the caller has to check. Also commits — a rate-limit hit must persist even if
    the caller's transaction later rolls back for an unrelated reason."""
    result = check_rate_limit(db, key=key, limit=limit, window_seconds=window_seconds)
    db.commit()
    if not result.allowed:
        raise RateLimited(
            f"Too many attempts. Try again after {result.reset_at.isoformat()}.",
        )
