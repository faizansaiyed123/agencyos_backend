"""Business logic for signup, login, token refresh and invites.

Pure/business functions take a Session and explicit arguments; they do not read
request/response objects. Cookie handling lives in the router.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.db import set_org_context
from app.core.errors import Conflict, Forbidden, NotFound, Unauthorized
from app.core.permissions import Role
from app.core.security import (
    burn_password_check,
    create_access_token,
    create_mfa_pending_token,
    decode_mfa_pending_token,
    hash_password,
    hash_token,
    new_opaque_token,
    verify_password,
)
from app.modules.identity import mfa, queries
from app.modules.identity.models import (
    Invite,
    MfaRecoveryCode,
    Organization,
    PasswordResetToken,
    RefreshToken,
    User,
)
from app.platform import jobs
from app.platform.audit import record_audit

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str, suffix: str) -> str:
    base = _SLUG_RE.sub("-", name.lower()).strip("-") or "org"
    return f"{base}-{suffix}"[:80]


class AuthResult:
    def __init__(self, user: User, access_token: str, expires_in: int, refresh_token: str) -> None:
        self.user = user
        self.access_token = access_token
        self.expires_in = expires_in
        self.refresh_token = refresh_token


@dataclass(frozen=True)
class LoginOutcome:
    """Result of a password check. Either MFA isn't required and `auth` carries
    real tokens, or it is and `mfa_pending_token` must be exchanged via
    mfa_verify() before any tokens are issued."""

    mfa_required: bool
    auth: AuthResult | None = None
    mfa_pending_token: str | None = None


def signup_organization(
    db: Session, *, organization_name: str, full_name: str, email: str, password: str
) -> AuthResult:
    """Creates an org and its first user (owner) in one transaction.

    The org id is generated client-side (rather than left to the DB default) so the
    RLS context can be set *before* the INSERT: the organizations table's WITH CHECK
    policy requires id = current_setting('app.org_id'), and that setting must exist
    before the row is written, not after.
    """
    org_id = uuid.uuid4()
    set_org_context(db, org_id)
    org = Organization(
        id=org_id, name=organization_name, slug=_slugify(organization_name, org_id.hex[:8])
    )
    db.add(org)
    db.flush()

    user = User(
        org_id=org.id,
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
        role=Role.OWNER.value,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("An account with this email already exists", code="email_taken") from exc

    record_audit(
        db, org_id=org.id, actor_user_id=user.id, action="user.signup",
        entity_type="user", entity_id=user.id,
    )  # fmt: skip
    access_token, expires_in = create_access_token(user.id, org.id)
    refresh_token = _issue_refresh_token(db, user, family_id=uuid.uuid4())
    db.commit()
    return AuthResult(user, access_token, expires_in, refresh_token)


def request_password_reset(db: Session, *, email: str) -> str | None:
    """Create a single-use password-reset token for an active user.
    Returns the raw token only to the caller so the email job can deliver it; the
    token itself is stored only as a hash. The public endpoint must return the
    same response whether the account exists or not.
    """
    normalized = email.lower()
    user = queries.find_user_by_email_for_login(db, normalized)
    if user is None or not user.is_active:
        db.rollback()
        return None

    set_org_context(db, user.org_id)
    queries.revoke_live_password_reset_tokens(db, user.org_id, user.id)

    raw, digest = new_opaque_token()
    expires_at = utcnow() + timedelta(minutes=get_settings().password_reset_ttl_minutes)
    db.add(
        PasswordResetToken(
            org_id=user.org_id,
            user_id=user.id,
            token_hash=digest,
            expires_at=expires_at,
        )
    )
    settings = get_settings()
    reset_url = f"{settings.app_base_url}/reset-password?token={raw}"
    jobs.enqueue(
        db,
        job_type="send_password_reset_email",
        org_id=user.org_id,
        payload={"email": user.email, "reset_url": reset_url},
    )
    db.commit()
    return raw


def reset_password(
    db: Session, *, raw_token: str, new_password: str
) -> None:
    digest = hash_token(raw_token)
    token = queries.find_password_reset_token(db, digest, lock=True)
    if token is None:
        db.rollback()
        raise Conflict("This password reset link is invalid or expired", code="invalid_reset_token")

    set_org_context(db, token.org_id)
    now = utcnow()
    if token.used_at is not None or token.expires_at <= now:
        db.rollback()
        raise Conflict("This password reset link is invalid or expired", code="invalid_reset_token")

    user = queries.get_user(db, token.org_id, token.user_id)
    if user is None or not user.is_active:
        db.rollback()
        raise Conflict("This password reset link is invalid or expired", code="invalid_reset_token")

    user.password_hash = hash_password(new_password)
    user.failed_login_count = 0
    user.locked_until = None
    token.used_at = now

    # Invalidate every existing refresh session so the new password closes old
    # long-lived sessions. Short-lived access JWTs naturally expire within their TTL.
    db.execute(
        RefreshToken.__table__.update()
        .where(
            RefreshToken.org_id == token.org_id,
            RefreshToken.user_id == token.user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    record_audit(
        db,
        org_id=token.org_id,
        actor_user_id=user.id,
        action="auth.password_reset",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()


def authenticate(db: Session, *, email: str, password: str) -> LoginOutcome:
    settings = get_settings()
    user = queries.find_user_by_email_for_login(db, email.lower())
    if user is None:
        burn_password_check(password)  # equalise timing whether or not the email exists
        db.rollback()
        raise Unauthorized("Invalid email or password", code="invalid_credentials")

    set_org_context(db, user.org_id)
    now = utcnow()

    if user.locked_until is not None and user.locked_until > now:
        db.rollback()
        raise Unauthorized("Account temporarily locked. Try again later.", code="account_locked")

    if not user.is_active:
        db.rollback()
        raise Unauthorized("Invalid email or password", code="invalid_credentials")

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
        db.commit()
        raise Unauthorized("Invalid email or password", code="invalid_credentials")

    user.failed_login_count = 0
    user.locked_until = None

    if user.mfa_enabled:
        # Password was correct, but don't issue real tokens or set last_login_at
        # yet — that happens in mfa_verify(), once the second factor also checks
        # out. No refresh cookie is set at this stage either (see the router).
        record_audit(
            db, org_id=user.org_id, actor_user_id=user.id, action="auth.password_ok_awaiting_mfa",
            entity_type="user", entity_id=user.id,
        )  # fmt: skip
        db.commit()
        pending = create_mfa_pending_token(user.id, user.org_id)
        return LoginOutcome(mfa_required=True, mfa_pending_token=pending)

    user.last_login_at = now
    record_audit(
        db, org_id=user.org_id, actor_user_id=user.id, action="user.login",
        entity_type="user", entity_id=user.id,
    )  # fmt: skip
    auth = _issue_tokens_and_commit(db, user)
    return LoginOutcome(mfa_required=False, auth=auth)


def mfa_verify(db: Session, *, pending_token: str, code: str) -> AuthResult:
    """Second step of MFA login: exchanges a valid mfa_pending_token + a correct
    TOTP or recovery code for real tokens."""
    user_id, org_id = decode_mfa_pending_token(pending_token)
    set_org_context(db, org_id)
    user = queries.get_user(db, org_id, user_id)
    if user is None or not user.is_active or not user.mfa_enabled:
        db.rollback()
        raise Unauthorized("Invalid or expired MFA session", code="invalid_mfa_pending_token")

    if not _check_mfa_code(db, user, code):
        db.rollback()
        raise Unauthorized("Incorrect authentication code", code="invalid_mfa_code")

    user.last_login_at = utcnow()
    record_audit(
        db, org_id=user.org_id, actor_user_id=user.id, action="user.login_mfa_verified",
        entity_type="user", entity_id=user.id,
    )  # fmt: skip
    return _issue_tokens_and_commit(db, user)


def _check_mfa_code(db: Session, user: User, code: str) -> bool:
    """Tries the code as a TOTP first, then as a recovery code. A matched
    recovery code is consumed (single use) even though this function itself
    doesn't commit — the caller commits as part of the same transaction."""
    if user.mfa_secret_encrypted is None:  # guaranteed non-None by the DB check constraint
        raise Unauthorized("MFA is not properly configured for this account")
    secret = decrypt_secret(user.mfa_secret_encrypted)
    if len(code) == 6 and code.isdigit() and mfa.verify_totp_code(secret=secret, code=code):
        return True

    code_hash = mfa.hash_recovery_code(code)
    recovery = queries.find_unused_recovery_code(db, user.org_id, user.id, code_hash)
    if recovery is not None:
        recovery.used_at = utcnow()
        record_audit(
            db, org_id=user.org_id, actor_user_id=user.id, action="auth.mfa_recovery_code_used",
            entity_type="user", entity_id=user.id,
        )  # fmt: skip
        return True
    return False


def _issue_tokens_and_commit(db: Session, user: User) -> AuthResult:
    access_token, expires_in = create_access_token(user.id, user.org_id)
    refresh_token = _issue_refresh_token(db, user, family_id=uuid.uuid4())
    db.commit()
    return AuthResult(user, access_token, expires_in, refresh_token)


def mfa_enroll_start(db: Session, *, org_id: uuid.UUID, user: User) -> tuple[str, str, str]:
    """Generates a fresh TOTP secret and stores it encrypted, WITHOUT enabling
    MFA — that only happens once mfa_enroll_confirm proves the user actually
    scanned it correctly. Calling this again before confirming just overwrites
    the pending secret (no harm; nothing was enabled yet)."""
    set_org_context(db, org_id)
    secret = mfa.generate_totp_secret()
    user.mfa_secret_encrypted = encrypt_secret(secret)
    db.commit()
    uri = mfa.provisioning_uri(
        secret=secret, account_email=user.email, issuer=get_settings().mfa_issuer_name
    )
    return secret, uri, mfa.qr_code_svg(uri)


def mfa_enroll_confirm(db: Session, *, org_id: uuid.UUID, user: User, code: str) -> list[str]:
    set_org_context(db, org_id)
    if user.mfa_secret_encrypted is None:
        raise Conflict("No MFA enrollment in progress", code="mfa_not_enrolling")
    if user.mfa_enabled:
        raise Conflict("MFA is already enabled", code="mfa_already_enabled")

    secret = decrypt_secret(user.mfa_secret_encrypted)
    if not mfa.verify_totp_code(secret=secret, code=code):
        raise Unauthorized("Incorrect authentication code", code="invalid_mfa_code")

    user.mfa_enabled = True
    user.mfa_enrolled_at = utcnow()

    settings = get_settings()
    plaintext_codes = mfa.generate_recovery_codes(settings.mfa_recovery_code_count)
    for plaintext in plaintext_codes:
        db.add(
            MfaRecoveryCode(
                org_id=org_id, user_id=user.id, code_hash=mfa.hash_recovery_code(plaintext)
            )
        )
    record_audit(
        db, org_id=org_id, actor_user_id=user.id, action="auth.mfa_enabled",
        entity_type="user", entity_id=user.id,
    )  # fmt: skip
    db.commit()
    return plaintext_codes


def mfa_disable(db: Session, *, org_id: uuid.UUID, user: User, password: str, code: str) -> None:
    """Requires BOTH the current password and a valid second factor — an
    attacker who only stole a live session token cannot turn MFA off."""
    set_org_context(db, org_id)
    if not user.mfa_enabled:
        raise Conflict("MFA is not enabled", code="mfa_not_enabled")
    if not verify_password(user.password_hash, password):
        raise Unauthorized("Incorrect password", code="invalid_credentials")
    if not _check_mfa_code(db, user, code):
        raise Unauthorized("Incorrect authentication code", code="invalid_mfa_code")

    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    user.mfa_enrolled_at = None
    queries.delete_all_recovery_codes(db, org_id, user.id)
    record_audit(
        db, org_id=org_id, actor_user_id=user.id, action="auth.mfa_disabled",
        entity_type="user", entity_id=user.id,
    )  # fmt: skip
    db.commit()


def _issue_refresh_token(db: Session, user: User, *, family_id: uuid.UUID) -> str:
    settings = get_settings()
    raw, digest = new_opaque_token()
    db.add(
        RefreshToken(
            org_id=user.org_id,
            user_id=user.id,
            family_id=family_id,
            token_hash=digest,
            expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    return raw


def refresh_access_token(db: Session, *, raw_refresh_token: str) -> AuthResult:
    """Rotates the refresh token. If a token that was already rotated (or revoked) is
    presented again, the whole family is revoked — that is the signal of token theft."""
    digest = hash_token(raw_refresh_token)
    token = queries.find_refresh_token_by_hash(db, digest, lock=True)
    if token is None:
        db.rollback()
        raise Unauthorized("Invalid refresh token", code="invalid_refresh_token")

    set_org_context(db, token.org_id)
    now = utcnow()

    if token.revoked_at is not None:
        # Reuse of a revoked token: revoke the entire family and force re-login.
        for sibling in queries.find_live_family_tokens(db, token.org_id, token.family_id):
            sibling.revoked_at = now
        record_audit(
            db, org_id=token.org_id, actor_user_id=token.user_id,
            action="auth.refresh_token_reuse_detected",
            entity_type="refresh_token", entity_id=token.id,
        )  # fmt: skip
        db.commit()
        raise Unauthorized("Refresh token has been revoked", code="refresh_token_reused")

    if token.expires_at <= now:
        db.rollback()
        raise Unauthorized("Refresh token expired", code="refresh_token_expired")

    user = queries.get_user(db, token.org_id, token.user_id)
    if user is None or not user.is_active:
        db.rollback()
        raise Unauthorized("Invalid refresh token", code="invalid_refresh_token")

    token.revoked_at = now
    new_raw = _issue_refresh_token(db, user, family_id=token.family_id)
    access_token, expires_in = create_access_token(user.id, user.org_id)
    db.commit()
    return AuthResult(user, access_token, expires_in, new_raw)


def revoke_refresh_token(db: Session, *, raw_refresh_token: str) -> None:
    digest = hash_token(raw_refresh_token)
    token = queries.find_refresh_token_by_hash(db, digest)
    if token is None:
        db.rollback()
        return
    set_org_context(db, token.org_id)
    token.revoked_at = utcnow()
    db.commit()


def create_invite(
    db: Session,
    *,
    org_id: uuid.UUID,
    invited_by: uuid.UUID,
    email: str,
    role: str,
    commit: bool = True,
) -> tuple[Invite, str]:
    set_org_context(db, org_id)
    existing = queries.find_pending_invite_by_email(db, org_id, email.lower())
    if existing is not None:
        existing.revoked_at = utcnow()

    raw, digest = new_opaque_token()
    settings = get_settings()
    invite = Invite(
        org_id=org_id,
        email=email.lower(),
        role=role,
        token_hash=digest,
        invited_by=invited_by,
        expires_at=utcnow() + timedelta(days=settings.invite_ttl_days),
    )
    db.add(invite)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(
            "An active invite already exists for this email", code="invite_exists"
        ) from exc

    record_audit(
        db, org_id=org_id, actor_user_id=invited_by, action="invite.created",
        entity_type="invite", entity_id=invite.id, data={"email": invite.email, "role": role},
    )  # fmt: skip

    # Transactional outbox: this INSERT lands in the SAME transaction as the
    # invite row above, so the email job exists if and only if the invite
    # itself committed — no risk of "invite created but no email queued" or
    # vice versa, and no dependency on an external mail service to do it.
    org = queries.get_organization(db, org_id)
    accept_url = f"{settings.app_base_url}/accept-invite?token={raw}"
    jobs.enqueue(
        db, job_type="send_invite_email", org_id=org_id,
        payload={
            "email": invite.email, "role": role, "accept_url": accept_url,
            "org_name": org.name if org else "your organization",
        },
    )  # fmt: skip

    if commit:
        db.commit()
    return invite, raw


def accept_invite(db: Session, *, raw_token: str, full_name: str, password: str) -> AuthResult:
    digest = hash_token(raw_token)
    invite = queries.find_invite_by_token(db, digest)
    if invite is None:
        db.rollback()
        raise NotFound("Invite not found or already used", code="invite_not_found")

    set_org_context(db, invite.org_id)
    now = utcnow()
    if invite.accepted_at is not None or invite.revoked_at is not None:
        db.rollback()
        raise Conflict("This invite is no longer valid", code="invite_invalid")
    if invite.expires_at <= now:
        db.rollback()
        raise Conflict("This invite has expired", code="invite_expired")

    user = User(
        org_id=invite.org_id,
        email=invite.email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=invite.role,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("An account with this email already exists", code="email_taken") from exc

    invite.accepted_at = now
    record_audit(
        db, org_id=invite.org_id, actor_user_id=user.id, action="invite.accepted",
        entity_type="user", entity_id=user.id,
    )  # fmt: skip

    access_token, expires_in = create_access_token(user.id, user.org_id)
    refresh_token = _issue_refresh_token(db, user, family_id=uuid.uuid4())
    db.commit()
    return AuthResult(user, access_token, expires_in, refresh_token)


def revoke_invite(
    db: Session, *, org_id: uuid.UUID, actor_user_id: uuid.UUID, invite_id: uuid.UUID
) -> None:
    set_org_context(db, org_id)
    invite = db.get(Invite, invite_id)
    if invite is None or invite.org_id != org_id:
        raise NotFound("Invite not found")
    if invite.accepted_at is not None:
        raise Conflict("Invite already accepted", code="invite_already_accepted")
    invite.revoked_at = utcnow()
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_user_id,
        action="invite.revoked",
        entity_type="invite",
        entity_id=invite.id,
    )
    db.commit()


def change_user_role(
    db: Session, *, org_id: uuid.UUID, actor: User, target_user_id: uuid.UUID, new_role: str
) -> User:
    if actor.role not in (Role.OWNER.value, Role.ADMIN.value):
        raise Forbidden("Only an owner or admin can change roles")
    if new_role not in {r.value for r in Role}:
        raise Conflict("Invalid role", code="invalid_role")

    set_org_context(db, org_id)
    target = queries.get_user(db, org_id, target_user_id)
    if target is None:
        raise NotFound("User not found")

    # An org must always keep at least one active owner.
    demoting_owner = target.role == Role.OWNER.value and new_role != Role.OWNER.value
    if demoting_owner and queries.count_active_owners(db, org_id) <= 1:
        raise Conflict("An organization must have at least one owner", code="last_owner")

    # Only an owner may promote someone else to owner.
    if new_role == Role.OWNER.value and actor.role != Role.OWNER.value:
        raise Forbidden("Only an owner can grant the owner role")

    target.role = new_role
    record_audit(
        db, org_id=org_id, actor_user_id=actor.id, action="user.role_changed",
        entity_type="user", entity_id=target.id, data={"new_role": new_role},
    )  # fmt: skip
    db.commit()
    return target
