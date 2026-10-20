"""Object-level access rule shared by comments, approvals and file attachments:
you may only attach to or discuss items you are allowed to see."""

import uuid

from sqlalchemy.orm import Session

from app.core.db import set_org_context
from app.core.errors import Forbidden, NotFound
from app.core.permissions import Perm, Role, has_permission
from app.modules.identity.models import User
from app.modules.projects import queries as project_queries

_READ_PERM = {
    "client": Perm.CLIENT_READ,
    "deal": Perm.DEAL_READ,
    "proposal": Perm.PROPOSAL_READ,
    "invoice": Perm.INVOICE_READ,
    "project": Perm.PROJECT_READ,
    "task": Perm.PROJECT_READ,
}


def authorize_entity(db: Session, user: User, entity_type: str, entity_id: uuid.UUID) -> None:
    """You may only discuss things you are allowed to see."""
    perm = _READ_PERM.get(entity_type)
    if perm is None or not has_permission(Role(user.role), perm):
        raise Forbidden("You do not have access to that item")
    if Role(user.role) == Role.TEAM_MEMBER and entity_type in ("project", "task"):
        set_org_context(db, user.org_id)
        project_id = entity_id
        if entity_type == "task":
            task = project_queries.get_task(db, user.org_id, entity_id)
            if task is None:
                raise NotFound("Task not found")
            project_id = task.project_id
        if (
            project_queries.get_project(
                db, user.org_id, project_id, user_id=user.id, restricted=True
            )
            is None
        ):
            raise NotFound("Project not found")
