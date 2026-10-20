"""Pydantic request/response models for the identity module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.permissions import ROLE_VALUES

_PASSWORD_MIN_LEN = 10


def _validate_password_strength(v: str) -> str:
    if len(v) < _PASSWORD_MIN_LEN:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LEN} characters")
    if v.lower() == v or v.upper() == v or not any(c.isdigit() for c in v):
        raise ValueError("Password must mix upper/lower case letters and at least one digit")
    return v


class SignupRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str

    _check_password = field_validator("password")(_validate_password_strength)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 token type, not a secret
    expires_in: int


class LoginResult(BaseModel):
    """Response shape for POST /auth/login. Exactly one of two states:
    - mfa_required is False: access_token/token_type/expires_in are populated,
      a refresh cookie was set, login is complete.
    - mfa_required is True: only mfa_pending_token is populated. No refresh
      cookie is set yet. The client must call POST /auth/mfa/verify with that
      token plus a TOTP or recovery code to actually get tokens.
    """

    mfa_required: bool
    access_token: str | None = None
    token_type: str | None = None  # noqa: S105
    expires_in: int | None = None
    mfa_pending_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    mfa_enabled: bool
    last_login_at: datetime | None
    created_at: datetime


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: str

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ROLE_VALUES or v == "owner":
            raise ValueError(f"role must be one of {[r for r in ROLE_VALUES if r != 'owner']}")
        return v


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InviteAcceptRequest(BaseModel):
    token: str
    full_name: str = Field(min_length=1, max_length=200)
    password: str

    _check_password = field_validator("password")(_validate_password_strength)


class MfaEnrollStartResponse(BaseModel):
    """The secret is shown once for manual entry; most users will just scan the
    QR code instead. Nothing here is persisted as 'enabled' until confirmed."""

    secret: str
    otpauth_uri: str
    qr_code_svg: str


class MfaEnrollConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MfaEnrollConfirmResponse(BaseModel):
    recovery_codes: list[str]


class MfaVerifyRequest(BaseModel):
    mfa_pending_token: str
    # Either a 6-digit TOTP code or an XXXX-XXXX recovery code.
    code: str = Field(min_length=6, max_length=9)


class MfaDisableRequest(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=9)


class MfaStatusOut(BaseModel):
    mfa_enabled: bool
    enrolled_at: datetime | None
    recovery_codes_remaining: int
