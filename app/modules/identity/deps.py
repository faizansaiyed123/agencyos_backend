"""FastAPI auth dependencies that DO know about `User` — this is the one place
other modules are meant to import from for "who is calling and are they allowed".

Two layers:
  - `current_user`: verifies the JWT, sets the RLS org context for this request's
    session, and loads the caller's fresh row (so a deactivated/role-changed user
    is rejected, or reflects the new role, immediately — nothing but the identity
    comes from the token itself).
  - `require(perm)` / `require_role(...)`: dependency factories for route-level
    checks. Object-level scoping (e.g. "only your own projects") happens in each
    module's queries, not here.

Other modules depend on identity for this (a one-way dependency, not a cycle) —
that is expected and is not what the "core must not depend on modules" contract
guards against.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.auth import bearer_token
from app.core.db import get_db, set_org_context
from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import Perm, Role, has_permission
from app.core.security import decode_access_token
from app.modules.identity.models import User


def current_user(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Depends(bearer_token)],
) -> User:
    user_id, org_id = decode_access_token(token)
    set_org_context(db, org_id)
    user = db.get(User, user_id)
    if user is None or user.org_id != org_id or not user.is_active:
        raise Unauthorized("Invalid or expired session")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(perm: Perm) -> Callable[[CurrentUser], User]:
    def _check(user: CurrentUser) -> User:
        if not has_permission(Role(user.role), perm):
            raise Forbidden(f"Role '{user.role}' lacks permission '{perm.value}'")
        return user

    return _check


def require_role(*roles: Role) -> Callable[[CurrentUser], User]:
    def _check(user: CurrentUser) -> User:
        if Role(user.role) not in roles:
            allowed = ", ".join(r.value for r in roles)
            raise Forbidden(f"This action requires one of: {allowed}")
        return user

    return _check
