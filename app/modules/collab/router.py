import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import Perm, Role, has_permission
from app.modules.collab import service, stream
from app.modules.collab.access import authorize_entity as _authorize_entity
from app.modules.collab.schemas import (
    ApprovalCreate,
    ApprovalDecision,
    ApprovalOut,
    CommentCreate,
    CommentEdit,
    CommentOut,
    MarkReadRequest,
    NotificationOut,
    StreamTicket,
)
from app.modules.identity.deps import CurrentUser, require
from app.modules.identity.models import User

router = APIRouter(tags=["collaboration"])
Db = Annotated[Session, Depends(get_db)]
Writer = Annotated[User, Depends(require(Perm.COMMENT_WRITE))]


@router.post("/comments", response_model=CommentOut, status_code=201)
def add_comment(body: CommentCreate, user: Writer, db: Db) -> CommentOut:
    _authorize_entity(db, user, body.entity_type, body.entity_id)
    c = service.add_comment(db, org_id=user.org_id, author_id=user.id, **body.model_dump())
    return CommentOut.model_validate(c)


@router.get("/comments", response_model=list[CommentOut])
def list_comments(entity_type: str, entity_id: uuid.UUID, user: Writer, db: Db) -> list[CommentOut]:
    _authorize_entity(db, user, entity_type, entity_id)
    return [
        CommentOut.model_validate(c)
        for c in service.list_comments(db, user.org_id, entity_type, entity_id)
    ]


@router.patch("/comments/{comment_id}", response_model=CommentOut)
def edit_comment(comment_id: uuid.UUID, body: CommentEdit, user: Writer, db: Db) -> CommentOut:
    return CommentOut.model_validate(
        service.edit_comment(
            db, org_id=user.org_id, user_id=user.id, comment_id=comment_id, body=body.body
        )
    )


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: uuid.UUID, user: Writer, db: Db) -> None:
    moderator = has_permission(Role(user.role), Perm.USER_MANAGE)
    service.delete_comment(
        db, org_id=user.org_id, user_id=user.id, can_moderate=moderator, comment_id=comment_id
    )


@router.post("/approvals", response_model=ApprovalOut, status_code=201)
def request_approval(
    body: ApprovalCreate, user: Annotated[User, Depends(require(Perm.APPROVAL_MANAGE))], db: Db
) -> ApprovalOut:
    _authorize_entity(db, user, body.entity_type, body.entity_id)
    r = service.request_approval(db, org_id=user.org_id, requester_id=user.id, **body.model_dump())
    return ApprovalOut.model_validate(r)


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(
    user: CurrentUser, db: Db, inbox: bool = False, status: str | None = None
) -> list[ApprovalOut]:
    rows = service.list_approvals(
        db, org_id=user.org_id, user_id=user.id, mine_to_decide=inbox, status=status
    )
    return [ApprovalOut.model_validate(r) for r in rows]


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalOut)
def decide(
    approval_id: uuid.UUID, body: ApprovalDecision, user: CurrentUser, db: Db
) -> ApprovalOut:
    r = service.decide(
        db,
        org_id=user.org_id,
        user_id=user.id,
        approval_id=approval_id,
        approve=body.approve,
        note=body.note,
    )
    return ApprovalOut.model_validate(r)


@router.post("/approvals/{approval_id}/cancel", response_model=ApprovalOut)
def cancel(approval_id: uuid.UUID, user: CurrentUser, db: Db) -> ApprovalOut:
    return ApprovalOut.model_validate(
        service.cancel(db, org_id=user.org_id, user_id=user.id, approval_id=approval_id)
    )


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(
    user: CurrentUser, db: Db, unread: bool = False, limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> list[NotificationOut]:
    rows = service.list_notifications(
        db, org_id=user.org_id, user_id=user.id, unread_only=unread, limit=limit
    )
    return [NotificationOut.model_validate(n) for n in rows]


@router.get("/notifications/unread-count")
def unread_count(user: CurrentUser, db: Db) -> dict[str, int]:
    return {"unread": service.unread_count(db, org_id=user.org_id, user_id=user.id)}


@router.post("/notifications/read")
def mark_read(body: MarkReadRequest, user: CurrentUser, db: Db) -> dict[str, int]:
    return {"marked": service.mark_read(db, org_id=user.org_id, user_id=user.id, ids=body.ids)}


@router.post("/notifications/stream-ticket", response_model=StreamTicket)
def stream_ticket(user: CurrentUser) -> StreamTicket:
    return StreamTicket(
        ticket=stream.issue_ticket(user.id, user.org_id), expires_in=stream.TICKET_TTL_SECONDS
    )


@router.get("/notifications/stream")
def notifications_stream(ticket: str) -> StreamingResponse:
    user_id, org_id = stream.verify_ticket(ticket)
    return StreamingResponse(
        stream.event_stream(org_id, user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
