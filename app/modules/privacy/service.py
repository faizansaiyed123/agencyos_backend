"""GDPR tooling: data export (access / portability) and erasure (right to be forgotten).

Erasure ANONYMISES rather than deletes the user row: invoices, time entries, audit
history and project records reference the user, and accounting/legal-retention duties
require those records to survive. Personal identifiers are removed instead:
name, email, credentials, MFA, sessions, notifications, and the text of comments."""

import secrets
import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.db import set_org_context
from app.core.errors import BusinessRuleViolation, NotFound
from app.core.security import hash_password
from app.modules.collab.models import ApprovalRequest, Comment
from app.modules.files.models import FileAsset
from app.modules.identity.models import MfaRecoveryCode, RefreshToken, User
from app.modules.projects.models import Task
from app.modules.time.models import TimeEntry
from app.platform.audit import AuditLog, record_audit
from app.platform.notifications import Notification

RETAINED = [
    "invoices and payments you created (accounting retention)",
    "time entries (billing evidence)",
    "audit log entries (security record, now showing an anonymised actor)",
]


def _row(obj: Any, *cols: str) -> dict[str, Any]:
    return {c: (str(getattr(obj, c)) if getattr(obj, c) is not None else None) for c in cols}


def export_user(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    set_org_context(db, org_id)
    u = db.get(User, user_id)
    if u is None or u.org_id != org_id:
        raise NotFound("User not found")

    def q(model: Any, cond: Any) -> list[Any]:
        stmt = select(model).where(model.org_id == org_id, cond).order_by(model.created_at)
        return list(db.scalars(stmt))

    return {
        "profile": _row(
            u,
            "id",
            "email",
            "full_name",
            "role",
            "is_active",
            "mfa_enabled",
            "last_login_at",
            "created_at",
        ),
        "time_entries": [
            _row(
                e, "id", "project_id", "entry_date", "minutes", "billable", "status", "description"
            )
            for e in q(TimeEntry, TimeEntry.user_id == user_id)
        ],
        "comments": [
            _row(c, "id", "entity_type", "entity_id", "body", "created_at")
            for c in q(Comment, Comment.author_id == user_id)
        ],
        "assigned_tasks": [
            _row(t, "id", "project_id", "title", "status", "due_date")
            for t in q(Task, Task.assignee_user_id == user_id)
        ],
        "notifications": [
            _row(n, "id", "kind", "title", "is_read", "created_at")
            for n in q(Notification, Notification.user_id == user_id)
        ],
        "approval_requests": [
            _row(a, "id", "title", "status", "created_at")
            for a in q(
                ApprovalRequest,
                (ApprovalRequest.requested_by == user_id)
                | (ApprovalRequest.approver_id == user_id),
            )
        ],
        "files_uploaded": [
            _row(f, "id", "filename", "size_bytes", "created_at")
            for f in q(FileAsset, FileAsset.uploaded_by == user_id)
        ],
        "audit_trail": [
            _row(a, "action", "entity_type", "entity_id", "created_at")
            for a in db.scalars(
                select(AuditLog)
                .where(AuditLog.org_id == org_id, AuditLog.actor_user_id == user_id)
                .order_by(AuditLog.created_at)
                .limit(5000)
            )
        ],
    }


def erase_user(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    set_org_context(db, org_id)
    u = db.scalar(select(User).where(User.org_id == org_id, User.id == user_id).with_for_update())
    if u is None:
        raise NotFound("User not found")
    if u.email.endswith("@erased.invalid"):
        raise BusinessRuleViolation("This user has already been erased", code="already_erased")
    if u.role == "owner" and u.is_active:
        owners = (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.org_id == org_id, User.role == "owner", User.is_active.is_(True))
            )
            or 0
        )
        if owners <= 1:
            raise BusinessRuleViolation(
                "Transfer ownership before erasing the last owner", code="last_owner"
            )
    u.email = f"erased+{u.id.hex}@erased.invalid"
    u.full_name = "Erased user"
    u.password_hash = hash_password(secrets.token_urlsafe(32))  # unusable: nobody knows it
    u.is_active = False
    u.mfa_enabled = False
    u.mfa_secret_encrypted = None
    u.mfa_enrolled_at = None
    db.execute(
        delete(RefreshToken).where(RefreshToken.org_id == org_id, RefreshToken.user_id == user_id)
    )
    db.execute(
        delete(MfaRecoveryCode).where(
            MfaRecoveryCode.org_id == org_id, MfaRecoveryCode.user_id == user_id
        )
    )
    db.execute(
        delete(Notification).where(Notification.org_id == org_id, Notification.user_id == user_id)
    )
    db.execute(
        update(Comment)
        .where(Comment.org_id == org_id, Comment.author_id == user_id)
        .values(body="[removed on request]", mentions=[])
    )
    db.execute(
        update(Task)
        .where(Task.org_id == org_id, Task.assignee_user_id == user_id, Task.status != "done")
        .values(assignee_user_id=None)
    )
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="privacy.user_erased",
        entity_type="user",
        entity_id=user_id,
    )
    db.commit()
    return {"user_id": str(user_id), "erased": True, "retained": RETAINED}
