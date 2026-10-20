"""A Postgres-native job queue implementing the transactional outbox pattern.
No external broker — see the migration `eb8c3f41d382` docstring for the full
rationale and the `claim_jobs()` SQL function this wraps.

Usage pattern (the outbox half): call `enqueue()` from WITHIN an existing
business transaction, before that transaction's own commit — e.g. inside
`identity.service.create_invite`, right before `db.commit()`. That is what
makes the job durable if and only if the business change it belongs to
actually committed; enqueue() does not commit anything itself.

Usage pattern (the worker half): a loop (see `run_worker_once`) claims a batch
via `claim_jobs()`, dispatches each job to a registered handler by
`job_type`, and marks it completed or failed (with exponential backoff, up to
`max_attempts`, after which it's parked in `dead_letter` for manual review).
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger()

JobHandler = Callable[[dict[str, Any], Session], None]

_HANDLERS: dict[str, JobHandler] = {}


def register_handler(job_type: str, handler: JobHandler) -> None:
    _HANDLERS[job_type] = handler


@dataclass(frozen=True)
class Job:
    id: uuid.UUID
    org_id: uuid.UUID | None
    job_type: str
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    run_after: datetime
    last_error: str | None


def enqueue(
    db: Session,
    *,
    job_type: str,
    payload: dict[str, Any],
    org_id: uuid.UUID | None = None,
    run_after: datetime | None = None,
) -> None:
    """Adds a pending job row. Deliberately does NOT commit — call this inside
    an existing transaction so the enqueue is atomic with whatever business
    change it accompanies (the outbox guarantee). `run_after` schedules a
    delayed job (e.g. 'expire this proposal on its valid_until date') instead
    of one meant to run as soon as a worker is free; omit it to run ASAP."""
    db.execute(
        text(
            "INSERT INTO jobs (org_id, job_type, payload, run_after) "
            "VALUES (:org_id, :job_type, CAST(:payload AS jsonb), COALESCE(:run_after, now()))"
        ),
        {
            "org_id": org_id,
            "job_type": job_type,
            "payload": _to_json(payload),
            "run_after": run_after,
        },
    )


def _to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


def _row_to_job(row: Any) -> Job:
    payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
    return Job(
        id=row.id, org_id=row.org_id, job_type=row.job_type, payload=payload,
        status=row.status, attempts=row.attempts, max_attempts=row.max_attempts,
        run_after=row.run_after, last_error=row.last_error,
    )  # fmt: skip


def claim_jobs(db: Session, *, limit: int, stale_after_seconds: int = 300) -> list[Job]:
    rows = db.execute(
        text("SELECT * FROM claim_jobs(:limit, :stale)"),
        {"limit": limit, "stale": stale_after_seconds},
    ).all()
    db.commit()
    return [_row_to_job(r) for r in rows]


def complete_job(db: Session, job_id: uuid.UUID) -> None:
    db.execute(
        text("UPDATE jobs SET status = 'completed', updated_at = now() WHERE id = :id"),
        {"id": job_id},
    )
    db.commit()


def _backoff_seconds(attempts: int) -> int:
    # 1, 2, 4, 8, 16... minutes, capped at 1 hour. Bit-shift instead of `**`:
    # typeshed's int.__pow__ overload resolution returns Any for a
    # non-literal exponent, which mypy --strict flags; left-shift is
    # unambiguously typed as int.
    return min(60 << attempts, 3600)


def fail_job(
    db: Session, job_id: uuid.UUID, *, attempts: int, max_attempts: int, error: str
) -> None:
    new_attempts = attempts + 1
    if new_attempts >= max_attempts:
        db.execute(
            text(
                "UPDATE jobs SET status = 'dead_letter', attempts = :a, last_error = :e, "
                "updated_at = now() WHERE id = :id"
            ),
            {"a": new_attempts, "e": error[:2000], "id": job_id},
        )
    else:
        db.execute(
            text(
                "UPDATE jobs SET status = 'pending', attempts = :a, last_error = :e, "
                "run_after = now() + make_interval(secs => :backoff), updated_at = now() "
                "WHERE id = :id"
            ),
            {
                "a": new_attempts,
                "e": error[:2000],
                "id": job_id,
                "backoff": _backoff_seconds(new_attempts),
            },
        )
    db.commit()


def run_worker_once(db: Session, *, batch_size: int = 10) -> int:
    """Claims and processes up to `batch_size` jobs synchronously. Returns the
    number processed (completed or failed, either counts). A real deployment
    calls this in a loop with a short sleep between empty batches; tests call
    it directly for deterministic, non-flaky assertions."""
    jobs = claim_jobs(db, limit=batch_size)
    for job in jobs:
        handler = _HANDLERS.get(job.job_type)
        if handler is None:
            fail_job(
                db, job.id, attempts=job.attempts, max_attempts=job.max_attempts,
                error=f"no handler registered for job_type={job.job_type!r}",
            )  # fmt: skip
            continue
        try:
            handler(job.payload, db)
        except Exception as exc:  # noqa: BLE001 — a handler's failure must never kill the worker loop
            log.warning("job_failed", job_id=str(job.id), job_type=job.job_type, error=str(exc))
            fail_job(
                db, job.id, attempts=job.attempts, max_attempts=job.max_attempts, error=str(exc)
            )
        else:
            complete_job(db, job.id)
    return len(jobs)
