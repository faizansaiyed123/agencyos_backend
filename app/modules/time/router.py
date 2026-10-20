import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import NotFound
from app.core.pagination import PageDep
from app.core.permissions import Perm, Role, has_permission
from app.modules.identity.deps import require
from app.modules.identity.models import User
from app.modules.time import service
from app.modules.time.schemas import (
    ApproveRequest,
    EntryOut,
    EntryUpdateRequest,
    ManualEntryRequest,
    SummaryRow,
    TimerStartRequest,
)

router = APIRouter(prefix="/time", tags=["time"])
Db = Annotated[Session, Depends(get_db)]
Logger = Annotated[User, Depends(require(Perm.TIME_LOG))]
Approver = Annotated[User, Depends(require(Perm.TIME_APPROVE))]


@router.post("/timer/start", response_model=EntryOut, status_code=201)
def start(body: TimerStartRequest, user: Logger, db: Db) -> EntryOut:
    return EntryOut.model_validate(
        service.start_timer(db, org_id=user.org_id, user_id=user.id, **body.model_dump())
    )


@router.post("/timer/stop", response_model=EntryOut)
def stop(user: Logger, db: Db) -> EntryOut:
    return EntryOut.model_validate(service.stop_timer(db, org_id=user.org_id, user_id=user.id))


@router.get("/timer", response_model=EntryOut | None)
def current(user: Logger, db: Db) -> EntryOut | None:
    from app.core.db import set_org_context

    set_org_context(db, user.org_id)
    t = service.running_timer(db, user.org_id, user.id)
    return EntryOut.model_validate(t) if t else None


@router.post("/entries", response_model=EntryOut, status_code=201)
def log(body: ManualEntryRequest, user: Logger, db: Db) -> EntryOut:
    return EntryOut.model_validate(
        service.log_manual(db, org_id=user.org_id, user_id=user.id, **body.model_dump())
    )


@router.get("/entries", response_model=list[EntryOut])
def entries(
    user: Logger,
    db: Db,
    page: PageDep,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: uuid.UUID | None = None,
) -> list[EntryOut]:
    can_all = has_permission(Role(user.role), Perm.TIME_READ_ALL)
    scope = user_id if can_all else user.id  # others only ever see their own time
    rows = service.list_entries(
        db,
        org_id=user.org_id,
        user_id=scope,
        project_id=project_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=page.limit,
        offset=page.offset,
    )
    return [EntryOut.model_validate(r) for r in rows]


@router.get("/summary", response_model=list[SummaryRow])
def summary(
    user: Logger,
    db: Db,
    project_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[SummaryRow]:
    can_all = has_permission(Role(user.role), Perm.TIME_READ_ALL)
    rows = service.list_entries(
        db,
        org_id=user.org_id,
        user_id=None if can_all else user.id,
        project_id=project_id,
        status=None,
        date_from=date_from,
        date_to=date_to,
        limit=100000,
        offset=0,
    )
    return [
        SummaryRow(project_id=p, user_id=u, minutes=m, billable_minutes=b, amount_cents=a)
        for (p, u), (m, b, a) in service.summarize(rows).items()
    ]


@router.patch("/entries/{entry_id}", response_model=EntryOut)
def update(entry_id: uuid.UUID, body: EntryUpdateRequest, user: Logger, db: Db) -> EntryOut:
    return EntryOut.model_validate(
        service.update_entry(
            db, org_id=user.org_id, user_id=user.id, entry_id=entry_id, **body.model_dump()
        )
    )


@router.delete("/entries/{entry_id}", status_code=204)
def delete(entry_id: uuid.UUID, user: Logger, db: Db) -> None:
    service.delete_entry(db, org_id=user.org_id, user_id=user.id, entry_id=entry_id)


@router.post("/approve", response_model=list[EntryOut])
def approve(body: ApproveRequest, user: Approver, db: Db) -> list[EntryOut]:
    rows = service.approve_entries(
        db, org_id=user.org_id, approver_id=user.id, entry_ids=body.entry_ids
    )
    return [EntryOut.model_validate(r) for r in rows]


__all__ = ["NotFound", "router"]
