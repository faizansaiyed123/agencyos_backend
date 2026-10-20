import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, created_at_col, updated_at_col, uuid_pk
from app.core.permissions import ROLE_VALUES

_ROLE_CHECK = "role IN (" + ", ".join(f"'{r}'" for r in ROLE_VALUES) + ")"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_users_org_id_id"),  # target of composite FKs
        ForeignKeyConstraint(
            ["org_id", "client_id"], ["clients.org_id", "clients.id"],
            name="fk_users_org_id_clients", ondelete="RESTRICT",
        ),
        CheckConstraint(_ROLE_CHECK, name="role_valid"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonneg"),
        # A user can never be MFA-enabled without a secret on file. Pending
        # enrollment (a secret generated but not yet confirmed, mfa_enabled still
        # false) is a legitimate intermediate state and is allowed — this is a
        # one-directional implication, not a biconditional.
        CheckConstraint(
            "mfa_enabled = false OR mfa_secret_encrypted IS NOT NULL",
            name="mfa_secret_present_when_enabled",
        ),
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # TOTP secret, Fernet-encrypted at rest (see app.core.crypto). NULL until enrolled
    # AND confirmed — a secret generated but never confirmed never sets mfa_enabled.
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(String(255))
    mfa_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class RefreshToken(Base):
    """Rotating refresh tokens. All tokens descended from one login share a family_id;
    presenting an already-rotated token revokes the whole family (theft detection)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], ondelete="CASCADE",
            name="fk_refresh_tokens_org_id_users",
        ),
        Index("ix_refresh_tokens_family_id", "family_id"),
        Index("ix_refresh_tokens_user_id", "user_id"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "invited_by"], ["users.org_id", "users.id"], ondelete="RESTRICT",
            name="fk_invites_org_id_users",
        ),
        ForeignKeyConstraint(
            ["org_id", "client_id"], ["clients.org_id", "clients.id"], ondelete="RESTRICT",
            name="fk_invites_org_id_clients",
        ),
        CheckConstraint(_ROLE_CHECK, name="role_valid"),
        # At most one live invite per email per org; re-inviting revokes the older one.
        Index(
            "uq_invites_pending_email",
            "org_id",
            func.lower(text("email")),
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class MfaRecoveryCode(Base):
    """Single-use backup codes issued when MFA is confirmed. Stored hashed (like
    refresh/invite tokens) — the plaintext is shown to the user exactly once, at
    generation time, and is unrecoverable after that."""

    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], ondelete="CASCADE",
            name="fk_mfa_recovery_codes_org_id_users",
        ),
        Index("ix_mfa_recovery_codes_user_id", "user_id"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class PasswordResetToken(Base):
    """Single-use, short-lived password recovery token. Only its hash is stored."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], ondelete="CASCADE",
            name="fk_password_reset_tokens_org_id_users",
        ),
        Index("ix_password_reset_tokens_user_id", "user_id"),
        Index("ix_password_reset_tokens_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
