"""Single source of 'now' so time-dependent logic is testable."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
