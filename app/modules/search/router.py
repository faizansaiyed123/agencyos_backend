from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Forbidden
from app.core.permissions import Role
from app.modules.identity.deps import CurrentUser
from app.modules.search import service
from app.platform import flags

router = APIRouter(tags=["search"])
Db = Annotated[Session, Depends(get_db)]


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.get("/search")
def search(
    user: CurrentUser, db: Db, q: Annotated[str, Query(min_length=2, max_length=200)]
) -> list[dict[str, Any]]:
    return service.search(db, org_id=user.org_id, user_id=user.id, role=Role(user.role), q=q)


@router.post("/assistant/ask")
def ask(body: AskIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    if not flags.is_enabled(db, user.org_id, user.id, "assistant"):
        raise Forbidden(
            "The assistant is not enabled for your organisation", code="feature_disabled"
        )
    return service.ask(
        db, org_id=user.org_id, user_id=user.id, role=Role(user.role), question=body.question
    )
