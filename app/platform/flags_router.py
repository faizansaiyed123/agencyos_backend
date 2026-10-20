from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import Perm
from app.modules.identity.deps import CurrentUser, require
from app.modules.identity.models import User
from app.platform import flags
from app.platform.audit import record_audit

router = APIRouter(prefix="/flags", tags=["flags"])
Db = Annotated[Session, Depends(get_db)]


class FlagOut(BaseModel):
    key: str
    description: str
    enabled: bool
    rollout_percent: int
    effective_for_me: bool


class FlagIn(BaseModel):
    enabled: bool
    rollout_percent: int = Field(default=100, ge=0, le=100)


@router.get("/me", response_model=dict[str, bool])
def my_flags(user: CurrentUser, db: Db) -> dict[str, bool]:
    return flags.evaluate_all(db, user.org_id, user.id)


@router.get("", response_model=list[FlagOut])
def all_flags(user: Annotated[User, Depends(require(Perm.FLAG_MANAGE))], db: Db) -> list[FlagOut]:
    rows = flags.list_flags(db, user.org_id)
    out: list[FlagOut] = []
    for key, (desc, default) in flags.REGISTRY.items():
        r = rows.get(key)
        out.append(
            FlagOut(
                key=key,
                description=desc,
                enabled=r.enabled if r else default,
                rollout_percent=r.rollout_percent if r else 100,
                effective_for_me=flags.is_enabled(db, user.org_id, user.id, key),
            )
        )
    return out


@router.put("/{key}", response_model=FlagOut)
def put_flag(
    key: str, body: FlagIn, user: Annotated[User, Depends(require(Perm.FLAG_MANAGE))], db: Db
) -> FlagOut:
    row = flags.set_flag(
        db,
        org_id=user.org_id,
        actor_id=user.id,
        key=key,
        enabled=body.enabled,
        rollout_percent=body.rollout_percent,
    )
    record_audit(
        db,
        org_id=user.org_id,
        actor_user_id=user.id,
        action="flag.changed",
        entity_type="feature_flag",
        data={"key": key, "enabled": body.enabled, "rollout": body.rollout_percent},
    )
    db.commit()
    return FlagOut(
        key=key,
        description=flags.REGISTRY[key][0],
        enabled=row.enabled,
        rollout_percent=row.rollout_percent,
        effective_for_me=flags.is_enabled(db, user.org_id, user.id, key),
    )
