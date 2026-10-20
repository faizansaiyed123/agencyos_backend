"""HTTP routes for the identity module: signup, login, MFA, refresh, invites, users."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.auth import refresh_token_cookie
from app.core.config import get_settings
from app.core.db import get_db
from app.core.pagination import Page, PageDep
from app.core.permissions import Perm
from app.modules.identity import queries, service
from app.modules.identity.deps import CurrentUser, require
from app.modules.identity.schemas import (
    InviteAcceptRequest,
    InviteCreateRequest,
    InviteOut,
    LoginRequest,
    LoginResult,
    MfaDisableRequest,
    MfaEnrollConfirmRequest,
    MfaEnrollConfirmResponse,
    MfaEnrollStartResponse,
    MfaStatusOut,
    MfaVerifyRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from app.platform import idempotency
from app.platform.rate_limit import enforce_rate_limit

router = APIRouter(tags=["identity"])

_REFRESH_COOKIE = "agencyos_rt"


def _client_ip(request: Request) -> str:
    # Trusts X-Forwarded-For only because a reverse proxy is assumed to sit in
    # front of this service in any real deployment and to strip/overwrite any
    # client-supplied value; direct exposure would need this hardened further.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        _REFRESH_COOKIE,
        raw_token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/v1/auth",
    )


def _auth_response(response: Response, result: service.AuthResult) -> TokenResponse:
    _set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(access_token=result.access_token, expires_in=result.expires_in)


@router.post("/auth/signup", response_model=TokenResponse, status_code=201)
def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    settings = get_settings()
    enforce_rate_limit(
        db, key=f"signup:ip:{_client_ip(request)}",
        limit=settings.signup_rate_limit_per_hour, window_seconds=3600,
    )  # fmt: skip
    result = service.signup_organization(
        db, organization_name=body.organization_name, full_name=body.full_name,
        email=body.email, password=body.password,
    )  # fmt: skip
    return _auth_response(response, result)


@router.post("/auth/login", response_model=LoginResult)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResult:
    settings = get_settings()
    ip = _client_ip(request)
    # Two independent limits: by IP (stops one attacker hammering many accounts)
    # and by email (stops credential stuffing against one account from many IPs).
    enforce_rate_limit(
        db, key=f"login:ip:{ip}", limit=settings.login_rate_limit_per_5min, window_seconds=300
    )
    enforce_rate_limit(
        db, key=f"login:email:{body.email.lower()}",
        limit=settings.login_rate_limit_per_5min, window_seconds=300,
    )  # fmt: skip

    outcome = service.authenticate(db, email=body.email, password=body.password)
    if outcome.mfa_required:
        return LoginResult(mfa_required=True, mfa_pending_token=outcome.mfa_pending_token)

    if outcome.auth is None:  # guaranteed non-None when mfa_required is False
        raise RuntimeError("authenticate() returned no tokens and did not require MFA")
    _set_refresh_cookie(response, outcome.auth.refresh_token)
    return LoginResult(
        mfa_required=False,
        access_token=outcome.auth.access_token,
        token_type="bearer",  # noqa: S106 — OAuth2 token type, not a secret
        expires_in=outcome.auth.expires_in,
    )


@router.post("/auth/password/forgot", status_code=202)
def password_forgot(
    body: PasswordResetRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    settings = get_settings()
    enforce_rate_limit(
        db,
        key=f"account-recovery-ip:{_client_ip(request)}",
        limit=settings.password_reset_rate_limit_per_hour,
        window_seconds=3600,
    )
    service.request_password_reset(db, email=body.email)
    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.post("/auth/password/reset", status_code=204)
def password_reset(
    body: PasswordResetConfirmRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    settings = get_settings()
    enforce_rate_limit(
        db,
        key=f"account-recovery-confirm-ip:{_client_ip(request)}",
        limit=settings.password_reset_rate_limit_per_hour,
        window_seconds=3600,
    )
    service.reset_password(db, raw_token=body.token, new_password=body.password)


@router.post("/auth/mfa/verify", response_model=TokenResponse)
def mfa_verify(
    body: MfaVerifyRequest, response: Response, db: Annotated[Session, Depends(get_db)]
) -> TokenResponse:
    result = service.mfa_verify(db, pending_token=body.mfa_pending_token, code=body.code)
    return _auth_response(response, result)


@router.post("/auth/mfa/enroll", response_model=MfaEnrollStartResponse)
def mfa_enroll(
    user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> MfaEnrollStartResponse:
    secret, uri, qr_svg = service.mfa_enroll_start(db, org_id=user.org_id, user=user)
    return MfaEnrollStartResponse(secret=secret, otpauth_uri=uri, qr_code_svg=qr_svg)


@router.post("/auth/mfa/enroll/confirm", response_model=MfaEnrollConfirmResponse)
def mfa_enroll_confirm(
    body: MfaEnrollConfirmRequest, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> MfaEnrollConfirmResponse:
    codes = service.mfa_enroll_confirm(db, org_id=user.org_id, user=user, code=body.code)
    return MfaEnrollConfirmResponse(recovery_codes=codes)


@router.post("/auth/mfa/disable", status_code=204)
def mfa_disable(
    body: MfaDisableRequest, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> None:
    service.mfa_disable(db, org_id=user.org_id, user=user, password=body.password, code=body.code)


@router.get("/auth/mfa/status", response_model=MfaStatusOut)
def mfa_status(user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> MfaStatusOut:
    remaining = (
        queries.count_unused_recovery_codes(db, user.org_id, user.id) if user.mfa_enabled else 0
    )
    return MfaStatusOut(
        mfa_enabled=user.mfa_enabled, enrolled_at=user.mfa_enrolled_at,
        recovery_codes_remaining=remaining,
    )  # fmt: skip


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    raw_token: Annotated[str, Depends(refresh_token_cookie)],
) -> TokenResponse:
    result = service.refresh_access_token(db, raw_refresh_token=raw_token)
    return _auth_response(response, result)


@router.post("/auth/logout", status_code=204)
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    raw_token: Annotated[str, Depends(refresh_token_cookie)],
) -> None:
    service.revoke_refresh_token(db, raw_refresh_token=raw_token)
    response.delete_cookie(_REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/users", response_model=Page[UserOut])
def list_users(
    user: Annotated[CurrentUser, Depends(require(Perm.USER_READ))],
    db: Annotated[Session, Depends(get_db)],
    page: PageDep,
) -> Page[UserOut]:
    items, total = queries.list_users(db, user.org_id, limit=page.limit, offset=page.offset)
    return Page(
        items=[UserOut.model_validate(i) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite(
    body: InviteCreateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.USER_INVITE))],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> InviteOut | JSONResponse:
    """Demonstrates Idempotency-Key support end to end: a client that retries this
    call (e.g. after a dropped connection) with the same key gets back the exact
    original response instead of creating a second invite."""
    request_fp = None
    if idempotency_key:
        request_fp = idempotency.fingerprint("POST", "/invites", body.model_dump_json().encode())
        try:
            idempotency.check_idempotency_key(
                db, org_id=user.org_id, key=idempotency_key, request_fp=request_fp
            )
        except idempotency.IdempotencyReplay as replay:
            return JSONResponse(status_code=replay.status, content=replay.body)

    invite, _raw_token = service.create_invite(
        db,
        org_id=user.org_id,
        invited_by=user.id,
        email=body.email,
        role=body.role,
        commit=not bool(idempotency_key),
    )
    # In production the raw token is emailed to the invitee, not returned in the API
    # response; the console email backend (dev only) logs it instead (see app.platform.email).
    result = InviteOut.model_validate(invite)

    if idempotency_key and request_fp:
        idempotency.store_idempotency_result(
            db, org_id=user.org_id, user_id=user.id, key=idempotency_key,
            request_fp=request_fp, status=201, body=result.model_dump(mode="json"),
        )  # fmt: skip
        db.commit()
    return result


@router.get("/invites", response_model=list[InviteOut])
def list_invites(
    user: Annotated[CurrentUser, Depends(require(Perm.USER_INVITE))],
    db: Annotated[Session, Depends(get_db)],
) -> list[InviteOut]:
    return [InviteOut.model_validate(i) for i in queries.list_invites(db, user.org_id)]


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(
    invite_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.USER_INVITE))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    service.revoke_invite(db, org_id=user.org_id, actor_user_id=user.id, invite_id=invite_id)


@router.post("/invites/accept", response_model=TokenResponse, status_code=201)
def accept_invite(
    body: InviteAcceptRequest, response: Response, db: Annotated[Session, Depends(get_db)]
) -> TokenResponse:
    result = service.accept_invite(
        db, raw_token=body.token, full_name=body.full_name, password=body.password
    )
    return _auth_response(response, result)


@router.post("/users/{user_id}/role", response_model=UserOut)
def change_role(
    user_id: uuid.UUID,
    new_role: str,
    user: Annotated[CurrentUser, Depends(require(Perm.USER_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    target = service.change_user_role(
        db, org_id=user.org_id, actor=user, target_user_id=user_id, new_role=new_role
    )
    return UserOut.model_validate(target)
