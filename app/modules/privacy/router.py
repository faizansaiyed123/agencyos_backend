import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import Perm
from app.modules.identity.deps import CurrentUser, require
from app.modules.identity.models import User
from app.modules.privacy import service
from app.platform.audit import record_audit

router = APIRouter(prefix="/privacy", tags=["privacy"])
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require(Perm.PRIVACY_MANAGE))]


@router.get("/export/me")
def export_me(user: CurrentUser, db: Db) -> dict[str, Any]:
    """Everyone may download their own data (GDPR art. 15/20)."""
    data = service.export_user(db, user.org_id, user.id)
    record_audit(
        db,
        org_id=user.org_id,
        actor_user_id=user.id,
        action="privacy.self_export",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    return data


@router.get("/export/{user_id}")
def export_user(user_id: uuid.UUID, admin: Admin, db: Db) -> dict[str, Any]:
    data = service.export_user(db, admin.org_id, user_id)
    record_audit(
        db,
        org_id=admin.org_id,
        actor_user_id=admin.id,
        action="privacy.export",
        entity_type="user",
        entity_id=user_id,
    )
    db.commit()
    return data


@router.post("/erase/{user_id}")
def erase(user_id: uuid.UUID, admin: Admin, db: Db) -> dict[str, Any]:
    return service.erase_user(db, org_id=admin.org_id, actor_id=admin.id, user_id=user_id)
