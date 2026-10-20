"""Plain data-access functions for the identity module.

Functions that take an `org_id` param additionally rely on RLS (the caller must
have called `set_org_context` first) as the second layer of tenant isolation;
the explicit filter is the first layer and keeps intent obvious in code review.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import set_lookup_key
from app.modules.identity.models import Invite, MfaRecoveryCode, Organization, RefreshToken, User


def find_user_by_email_for_login(db: Session, email: str) -> User | None:
    """Unscoped lookup (org not yet known). Relies on the `login_lookup` RLS policy,
    which only ever permits SELECT and only when the lookup key is set."""
    set_lookup_key(db, email)
    return db.scalar(select(User).where(User.email.ilike(email)))


def get_user(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
    return db.scalar(select(User).where(User.org_id == org_id, User.id == user_id))


def list_users(
    db: Session, org_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[User], int]:
    items = list(
        db.scalars(
            select(User)
            .where(User.org_id == org_id)
            .order_by(User.created_at)
            .limit(limit)
            .offset(offset)
        )
    )
    return items, count_users(db, org_id)


def count_users(db: Session, org_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.org_id == org_id)) or 0


def count_active_owners(db: Session, org_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.org_id == org_id, User.role == "owner", User.is_active.is_(True))
        )
        or 0
    )


def get_organization(db: Session, org_id: uuid.UUID) -> Organization | None:
    return db.get(Organization, org_id)


def find_refresh_token_by_hash(
    db: Session, token_hash: str, *, lock: bool = False
) -> RefreshToken | None:
    set_lookup_key(db, token_hash)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def find_live_family_tokens(
    db: Session, org_id: uuid.UUID, family_id: uuid.UUID
) -> list[RefreshToken]:
    return list(
        db.scalars(
            select(RefreshToken).where(
                RefreshToken.org_id == org_id,
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
    )


def find_invite_by_token(db: Session, token_hash: str) -> Invite | None:
    set_lookup_key(db, token_hash)
    return db.scalar(select(Invite).where(Invite.token_hash == token_hash))


def find_pending_invite_by_email(db: Session, org_id: uuid.UUID, email: str) -> Invite | None:
    return db.scalar(
        select(Invite).where(
            Invite.org_id == org_id,
            Invite.email.ilike(email),
            Invite.accepted_at.is_(None),
            Invite.revoked_at.is_(None),
        )
    )


def list_invites(db: Session, org_id: uuid.UUID) -> list[Invite]:
    return list(
        db.scalars(select(Invite).where(Invite.org_id == org_id).order_by(Invite.created_at.desc()))
    )


def find_unused_recovery_code(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID, code_hash: str
) -> MfaRecoveryCode | None:
    return db.scalar(
        select(MfaRecoveryCode).where(
            MfaRecoveryCode.org_id == org_id,
            MfaRecoveryCode.user_id == user_id,
            MfaRecoveryCode.code_hash == code_hash,
            MfaRecoveryCode.used_at.is_(None),
        )
    )


def count_unused_recovery_codes(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.org_id == org_id,
                MfaRecoveryCode.user_id == user_id,
                MfaRecoveryCode.used_at.is_(None),
            )
        )
        or 0
    )


def delete_all_recovery_codes(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db.query(MfaRecoveryCode).filter(
        MfaRecoveryCode.org_id == org_id, MfaRecoveryCode.user_id == user_id
    ).delete()
