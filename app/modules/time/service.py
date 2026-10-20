"""Time tracking business logic."""

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import set_org_context
from app.core.errors import BusinessRuleViolation, Conflict, Forbidden, NotFound
from app.modules.projects import queries as project_queries
from app.modules.projects.models import ProjectMember
from app.modules.projects.project_states import is_terminal
from app.modules.time.models import TimeEntry, amount_cents
from app.platform import events
from app.platform.audit import record_audit
from app.platform.notifications import notify


def _loggable_project(
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
) -> ProjectMember:
    project = project_queries.get_project(db, org_id, project_id, user_id=user_id, restricted=False)
    if project is None:
        raise NotFound("Project not found")
    if is_terminal(project.status):
        raise Conflict(f"Project is {project.status}", code="project_closed")
    member = project_queries.get_member(db, org_id, project_id, user_id)
    if member is None:
        raise BusinessRuleViolation("You are not on this project's team", code="not_project_member")
    if task_id is not None:
        task = project_queries.get_task(db, org_id, task_id)
        if task is None or task.project_id != project_id:
            raise BusinessRuleViolation("Task is not part of this project", code="task_mismatch")
    return member


def get_entry(db: Session, org_id: uuid.UUID, entry_id: uuid.UUID) -> TimeEntry | None:
    return db.scalar(select(TimeEntry).where(TimeEntry.org_id == org_id, TimeEntry.id == entry_id))


def running_timer(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> TimeEntry | None:
    return db.scalar(
        select(TimeEntry).where(
            TimeEntry.org_id == org_id, TimeEntry.user_id == user_id, TimeEntry.ended_at.is_(None)
        )
    )


def start_timer(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    description: str | None,
    billable: bool,
) -> TimeEntry:
    set_org_context(db, org_id)
    member = _loggable_project(db, org_id, user_id, project_id, task_id)
    if running_timer(db, org_id, user_id) is not None:
        raise Conflict("You already have a running timer", code="timer_already_running")
    now = utcnow()
    entry = TimeEntry(
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        task_id=task_id,
        description=description,
        entry_date=now.date(),
        started_at=now,
        minutes=0,
        billable=billable,
        rate_cents=member.hourly_rate_cents,
    )
    db.add(entry)
    try:
        db.flush()  # the partial unique index is the backstop for a concurrent double-start
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("You already have a running timer", code="timer_already_running") from exc
    db.commit()
    return entry


def stop_timer(db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID) -> TimeEntry:
    set_org_context(db, org_id)
    entry = running_timer(db, org_id, user_id)
    if entry is None:
        raise NotFound("No running timer")
    now = utcnow()
    seconds = max(0, int((now - entry.started_at).total_seconds()))
    entry.ended_at = now
    entry.minutes = min(1440, max(1, -(-seconds // 60)))  # round up, at least a minute
    db.commit()
    return entry


def log_manual(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    description: str | None,
    entry_date: date,
    minutes: int,
    billable: bool,
) -> TimeEntry:
    set_org_context(db, org_id)
    member = _loggable_project(db, org_id, user_id, project_id, task_id)
    if entry_date > utcnow().date():
        raise BusinessRuleViolation("Cannot log time in the future", code="future_entry")
    total = sum(
        e.minutes
        for e in db.scalars(
            select(TimeEntry).where(
                TimeEntry.org_id == org_id,
                TimeEntry.user_id == user_id,
                TimeEntry.entry_date == entry_date,
            )
        )
    )
    if total + minutes > 1440:
        raise BusinessRuleViolation("That would exceed 24 hours in a day", code="day_overflow")
    now = utcnow()
    entry = TimeEntry(
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        task_id=task_id,
        description=description,
        entry_date=entry_date,
        started_at=now,
        ended_at=now,
        minutes=minutes,
        billable=billable,
        rate_cents=member.hourly_rate_cents,
    )
    db.add(entry)
    db.flush()
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=user_id,
        action="time.logged",
        entity_type="time_entry",
        entity_id=entry.id,
        data={"minutes": minutes},
    )
    db.commit()
    return entry


def _own_draft(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID, entry_id: uuid.UUID
) -> TimeEntry:
    entry = get_entry(db, org_id, entry_id)
    if entry is None or entry.user_id != user_id:
        raise NotFound("Time entry not found")
    if entry.status != "draft":
        raise Conflict(f"Entry is {entry.status} and can no longer be changed", code="entry_locked")
    if entry.ended_at is None:
        raise Conflict("Stop the timer first", code="timer_running")
    return entry


def update_entry(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    entry_id: uuid.UUID,
    description: str | None,
    entry_date: date | None,
    minutes: int | None,
    billable: bool | None,
    task_id: uuid.UUID | None,
) -> TimeEntry:
    set_org_context(db, org_id)
    entry = _own_draft(db, org_id, user_id, entry_id)
    if description is not None:
        entry.description = description
    if entry_date is not None:
        if entry_date > utcnow().date():
            raise BusinessRuleViolation("Cannot log time in the future", code="future_entry")
        entry.entry_date = entry_date
    if minutes is not None:
        entry.minutes = minutes
    if billable is not None:
        entry.billable = billable
    if task_id is not None:
        task = project_queries.get_task(db, org_id, task_id)
        if task is None or task.project_id != entry.project_id:
            raise BusinessRuleViolation("Task is not part of this project", code="task_mismatch")
        entry.task_id = task_id
    db.commit()
    return entry


def delete_entry(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, entry_id: uuid.UUID
) -> None:
    set_org_context(db, org_id)
    entry = get_entry(db, org_id, entry_id)
    if entry is None or entry.user_id != user_id:
        raise NotFound("Time entry not found")
    if entry.status != "draft":
        raise Conflict(f"Entry is {entry.status} and can no longer be deleted", code="entry_locked")
    db.delete(entry)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=user_id,
        action="time.deleted",
        entity_type="time_entry",
        entity_id=entry.id,
    )
    db.commit()


def approve_entries(
    db: Session, *, org_id: uuid.UUID, approver_id: uuid.UUID, entry_ids: list[uuid.UUID]
) -> list[TimeEntry]:
    """All-or-nothing: either every entry is approvable or none changes."""
    set_org_context(db, org_id)
    entries = [get_entry(db, org_id, i) for i in dict.fromkeys(entry_ids)]
    for e in entries:
        if e is None:
            raise NotFound("Time entry not found")
        if e.user_id == approver_id:
            raise Forbidden("You cannot approve your own time")
        if e.ended_at is None:
            raise Conflict("A running timer cannot be approved", code="timer_running")
        if e.status != "draft":
            raise Conflict(f"Entry is already {e.status}", code="invalid_status_transition")
    now = utcnow()
    approved: list[TimeEntry] = []
    for e in entries:
        assert e is not None  # noqa: S101 — narrowed by the loop above
        e.status = "approved"
        e.approved_by = approver_id
        e.approved_at = now
        approved.append(e)
        notify(
            db,
            org_id=org_id,
            user_id=e.user_id,
            kind="time_approved",
            title=f"Your {e.minutes} min entry was approved",
            entity_type="project",
            entity_id=e.project_id,
        )
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=approver_id,
        action="time.approved",
        entity_type="time_entry",
        data={"count": len(approved)},
    )
    events.emit(
        db,
        org_id=org_id,
        event_type="time.approved",
        data={"entry_ids": [str(e.id) for e in approved]},
    )
    db.commit()
    return approved


def list_entries(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> list[TimeEntry]:
    set_org_context(db, org_id)
    conds = [TimeEntry.org_id == org_id]
    if user_id:
        conds.append(TimeEntry.user_id == user_id)
    if project_id:
        conds.append(TimeEntry.project_id == project_id)
    if status:
        conds.append(TimeEntry.status == status)
    if date_from:
        conds.append(TimeEntry.entry_date >= date_from)
    if date_to:
        conds.append(TimeEntry.entry_date <= date_to)
    stmt = (
        select(TimeEntry)
        .where(*conds)
        .order_by(TimeEntry.entry_date.desc(), TimeEntry.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


def summarize(entries: list[TimeEntry]) -> dict[tuple[uuid.UUID, uuid.UUID], tuple[int, int, int]]:
    out: dict[tuple[uuid.UUID, uuid.UUID], tuple[int, int, int]] = {}
    for e in entries:
        m, b, a = out.get((e.project_id, e.user_id), (0, 0, 0))
        out[(e.project_id, e.user_id)] = (
            m + e.minutes,
            b + (e.minutes if e.billable else 0),
            a + (amount_cents(e.minutes, e.rate_cents) if e.billable else 0),
        )
    return out


def now_for_tests() -> datetime:  # pragma: no cover
    return utcnow()
