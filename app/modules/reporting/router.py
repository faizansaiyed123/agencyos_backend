import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import NotFound
from app.core.permissions import Perm
from app.modules.identity.deps import require
from app.modules.identity.models import User
from app.modules.reporting import service

router = APIRouter(prefix="/reports", tags=["reports"])
Db = Annotated[Session, Depends(get_db)]
Viewer = Annotated[User, Depends(require(Perm.REPORT_READ))]


@router.get("/overview")
def overview(user: Viewer, db: Db) -> dict[str, Any]:
    return service.overview(db, user.org_id)


@router.get("/attention")
def attention(user: Viewer, db: Db) -> list[dict[str, Any]]:
    return service.attention(db, user.org_id)


@router.get("/revenue")
def revenue(
    user: Viewer, db: Db, months: Annotated[int, Query(ge=1, le=36)] = 12
) -> list[dict[str, Any]]:
    return service.revenue_by_month(db, user.org_id, months)


@router.get("/pipeline")
def pipeline(user: Viewer, db: Db) -> dict[str, Any]:
    return service.pipeline(db, user.org_id)


@router.get("/utilization")
def utilization(
    user: Viewer, db: Db, date_from: date | None = None, date_to: date | None = None
) -> list[dict[str, Any]]:
    end = date_to or utcnow().date()
    return service.utilization(db, user.org_id, date_from or end - timedelta(days=30), end)


@router.get("/projects/{project_id}")
def project_health(project_id: uuid.UUID, user: Viewer, db: Db) -> dict[str, Any]:
    r = service.project_health(db, user.org_id, project_id)
    if r is None:
        raise NotFound("Project not found")
    return r
