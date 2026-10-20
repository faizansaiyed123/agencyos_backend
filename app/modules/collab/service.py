"""Collaboration logic: comments, @mentions, approvals and notification queries."""

import re
import uuid

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import set_org_context
from app.core.errors import BusinessRuleViolation, Conflict, Forbidden, NotFound
from app.modules.collab.models import ENTITY_TYPES, ApprovalRequest, Comment
from app.modules.identity.models import User
from app.platform import events
from app.platform.audit import record_audit
from app.platform.notifications import Notification, channel_for, notify

_MENTION = re.compile(r"@([\w.+-]+@[\w-]+\.[\w.-]+)")


def entity_exists(db: Session, org_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID) -> bool:
    if entity_type not in ENTITY_TYPES:
        raise BusinessRuleViolation(
            f"Unsupported entity type '{entity_type}'", code="bad_entity_type"
        )
    table = {
        "project": "projects",
        "task": "tasks",
        "client": "clients",
        "deal": "deals",
        "proposal": "proposals",
        "invoice": "invoices",
    }[entity_type]
    # `table` comes from the fixed map above, never from user input; values are bound.
    stmt = text(f"SELECT 1 FROM {table} WHERE org_id = :o AND id = :i")  # noqa: S608
    row = db.execute(stmt, {"o": org_id, "i": entity_id}).first()
    return row is not None


def add_comment(
    db: Session,
    *,
    org_id: uuid.UUID,
    author_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    body: str,
) -> Comment:
    set_org_context(db, org_id)
    if not entity_exists(db, org_id, entity_type, entity_id):
        raise NotFound(f"{entity_type.capitalize()} not found")
    emails = {m.lower() for m in _MENTION.findall(body)}
    mentioned: list[User] = []
    if emails:
        mentioned = list(
            db.scalars(
                select(User).where(
                    User.org_id == org_id,
                    func.lower(User.email).in_(emails),
                    User.is_active.is_(True),
                )
            )
        )
    comment = Comment(
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        author_id=author_id,
        body=body,
        mentions=[str(u.id) for u in mentioned],
    )
    db.add(comment)
    db.flush()
    for u in mentioned:
        if u.id != author_id:
            notify(
                db,
                org_id=org_id,
                user_id=u.id,
                kind="mention",
                title="You were mentioned in a comment",
                entity_type=entity_type,
                entity_id=entity_id,
            )
    db.commit()
    return comment


def list_comments(
    db: Session, org_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
) -> list[Comment]:
    set_org_context(db, org_id)
    return list(
        db.scalars(
            select(Comment)
            .where(
                Comment.org_id == org_id,
                Comment.entity_type == entity_type,
                Comment.entity_id == entity_id,
            )
            .order_by(Comment.created_at)
        )
    )


def edit_comment(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, comment_id: uuid.UUID, body: str
) -> Comment:
    set_org_context(db, org_id)
    c = db.scalar(select(Comment).where(Comment.org_id == org_id, Comment.id == comment_id))
    if c is None:
        raise NotFound("Comment not found")
    if c.author_id != user_id:
        raise Forbidden("You can only edit your own comments")
    c.body = body
    c.edited_at = utcnow()
    db.commit()
    return c


def delete_comment(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, can_moderate: bool, comment_id: uuid.UUID
) -> None:
    set_org_context(db, org_id)
    c = db.scalar(select(Comment).where(Comment.org_id == org_id, Comment.id == comment_id))
    if c is None:
        raise NotFound("Comment not found")
    if c.author_id != user_id and not can_moderate:
        raise Forbidden("You can only delete your own comments")
    db.delete(c)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=user_id,
        action="comment.deleted",
        entity_type="comment",
        entity_id=c.id,
    )
    db.commit()


# --- approvals ----------------------------------------------------------------------


def request_approval(
    db: Session,
    *,
    org_id: uuid.UUID,
    requester_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    approver_id: uuid.UUID,
    title: str,
) -> ApprovalRequest:
    set_org_context(db, org_id)
    if not entity_exists(db, org_id, entity_type, entity_id):
        raise NotFound(f"{entity_type.capitalize()} not found")
    if approver_id == requester_id:
        raise BusinessRuleViolation(
            "You cannot request approval from yourself", code="self_approval"
        )
    approver = db.get(User, approver_id)
    if approver is None or approver.org_id != org_id or not approver.is_active:
        raise BusinessRuleViolation(
            "Approver not found in this organization", code="user_not_found"
        )
    pending = db.scalar(
        select(ApprovalRequest.id).where(
            ApprovalRequest.org_id == org_id,
            ApprovalRequest.entity_type == entity_type,
            ApprovalRequest.entity_id == entity_id,
            ApprovalRequest.approver_id == approver_id,
            ApprovalRequest.status == "pending",
        )
    )
    if pending is not None:
        raise Conflict("An approval from this person is already pending", code="approval_pending")
    req = ApprovalRequest(
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
        requested_by=requester_id,
        approver_id=approver_id,
    )
    db.add(req)
    db.flush()
    notify(
        db,
        org_id=org_id,
        user_id=approver_id,
        kind="approval_requested",
        title=f"Approval requested: {title}",
        entity_type=entity_type,
        entity_id=entity_id,
    )
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=requester_id,
        action="approval.requested",
        entity_type="approval",
        entity_id=req.id,
    )
    events.emit(
        db,
        org_id=org_id,
        event_type="approval.requested",
        data={"approval_id": str(req.id), "entity_type": entity_type, "entity_id": str(entity_id)},
    )
    db.commit()
    return req


def decide(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    approval_id: uuid.UUID,
    approve: bool,
    note: str | None,
) -> ApprovalRequest:
    set_org_context(db, org_id)
    req = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.org_id == org_id, ApprovalRequest.id == approval_id)
        .with_for_update()
    )
    if req is None:
        raise NotFound("Approval request not found")
    if req.approver_id != user_id:
        raise Forbidden("Only the assigned approver can decide this request")
    if req.status != "pending":
        raise Conflict(f"This request is already {req.status}", code="approval_decided")
    if not approve and not (note and note.strip()):
        raise BusinessRuleViolation("Say why you are rejecting it", code="rejection_needs_note")
    req.status = "approved" if approve else "rejected"
    req.decision_note = note
    req.decided_at = utcnow()
    notify(
        db,
        org_id=org_id,
        user_id=req.requested_by,
        kind="approval_decided",
        title=f"{'Approved' if approve else 'Rejected'}: {req.title}",
        entity_type=req.entity_type,
        entity_id=req.entity_id,
    )
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=user_id,
        action=f"approval.{req.status}",
        entity_type="approval",
        entity_id=req.id,
    )
    events.emit(
        db,
        org_id=org_id,
        event_type="approval.decided",
        data={"approval_id": str(req.id), "status": req.status},
    )
    db.commit()
    return req


def cancel(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, approval_id: uuid.UUID
) -> ApprovalRequest:
    set_org_context(db, org_id)
    req = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.org_id == org_id, ApprovalRequest.id == approval_id)
        .with_for_update()
    )
    if req is None:
        raise NotFound("Approval request not found")
    if req.requested_by != user_id:
        raise Forbidden("Only the requester can cancel this request")
    if req.status != "pending":
        raise Conflict(f"This request is already {req.status}", code="approval_decided")
    req.status = "cancelled"
    db.commit()
    return req


def list_approvals(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, mine_to_decide: bool, status: str | None
) -> list[ApprovalRequest]:
    set_org_context(db, org_id)
    col = ApprovalRequest.approver_id if mine_to_decide else ApprovalRequest.requested_by
    conds = [ApprovalRequest.org_id == org_id, col == user_id]
    if status:
        conds.append(ApprovalRequest.status == status)
    return list(
        db.scalars(
            select(ApprovalRequest).where(*conds).order_by(ApprovalRequest.created_at.desc())
        )
    )


# --- notifications --------------------------------------------------------------------


def list_notifications(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, unread_only: bool, limit: int
) -> list[Notification]:
    set_org_context(db, org_id)
    conds = [Notification.org_id == org_id, Notification.user_id == user_id]
    if unread_only:
        conds.append(Notification.is_read.is_(False))
    return list(
        db.scalars(
            select(Notification).where(*conds).order_by(Notification.created_at.desc()).limit(limit)
        )
    )


def unread_count(db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    set_org_context(db, org_id)
    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.org_id == org_id,
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
        )
        or 0
    )


def mark_read(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, ids: list[uuid.UUID] | None
) -> int:
    set_org_context(db, org_id)
    stmt = update(Notification).where(
        Notification.org_id == org_id,
        Notification.user_id == user_id,
        Notification.is_read.is_(False),
    )
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    result = db.execute(stmt.values(is_read=True))
    db.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


__all__ = ["channel_for", "notify"]
