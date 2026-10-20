"""Generic, model-free authentication plumbing shared by every module.

This file deliberately knows nothing about `User` or any other module's model —
`app.core` must not depend on `app.modules` (enforced by import-linter). The
identity module builds the actual `current_user`/`require` dependencies on top
of `_bearer_token` below; see app.modules.identity.deps.
"""

from typing import Annotated

from fastapi import Cookie, Header

from app.core.errors import Unauthorized


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def refresh_token_cookie(agencyos_rt: Annotated[str | None, Cookie()] = None) -> str:
    if not agencyos_rt:
        raise Unauthorized("Missing refresh token", code="missing_refresh_token")
    return agencyos_rt
