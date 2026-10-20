"""Data access for projects. Visibility rule: a team_member only sees projects
they belong to; every other staff role with project:read sees all of the org."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.projects.models import Milestone, Project, ProjectMember, Task


def _visible(org_id: uuid.UUID, user_id: uuid.UUID, restricted: bool) -> list:  # type: ignore[type-arg]
    conds = [Project.org_id == org_id]
    if restricted:
        conds.append(
            Project.id.in_(
                select(ProjectMember.project_id).where(
                    ProjectMember.org_id == org_id, ProjectMember.user_id == user_id
                )
            )
        )
    return conds


def get_project(
    db: Session, org_id: uuid.UUID, project_id: uuid.UUID, *, user_id: uuid.UUID, restricted: bool
) -> Project | None:
    return db.scalar(
        select(Project).where(*_visible(org_id, user_id, restricted), Project.id == project_id)
    )


def list_projects(
    db: Session,
    org_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    restricted: bool,
    status: str | None,
    client_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[Project], int]:
    conds = _visible(org_id, user_id, restricted)
    if status:
        conds.append(Project.status == status)
    if client_id:
        conds.append(Project.client_id == client_id)
    items = list(
        db.scalars(
            select(Project)
            .where(*conds)
            .order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    total = db.scalar(select(func.count()).select_from(Project).where(*conds)) or 0
    return items, total


def get_project_for_deal(db: Session, org_id: uuid.UUID, deal_id: uuid.UUID) -> Project | None:
    return db.scalar(select(Project).where(Project.org_id == org_id, Project.deal_id == deal_id))


def list_members(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> list[ProjectMember]:
    return list(
        db.scalars(
            select(ProjectMember).where(
                ProjectMember.org_id == org_id, ProjectMember.project_id == project_id
            )
        )
    )


def get_member(
    db: Session, org_id: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectMember | None:
    return db.scalar(
        select(ProjectMember).where(
            ProjectMember.org_id == org_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )


def list_milestones(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> list[Milestone]:
    return list(
        db.scalars(
            select(Milestone)
            .where(Milestone.org_id == org_id, Milestone.project_id == project_id)
            .order_by(Milestone.position, Milestone.created_at)
        )
    )


def get_milestone(db: Session, org_id: uuid.UUID, milestone_id: uuid.UUID) -> Milestone | None:
    return db.scalar(
        select(Milestone).where(Milestone.org_id == org_id, Milestone.id == milestone_id)
    )


def get_task(db: Session, org_id: uuid.UUID, task_id: uuid.UUID) -> Task | None:
    return db.scalar(select(Task).where(Task.org_id == org_id, Task.id == task_id))


def list_tasks(
    db: Session,
    org_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[Task]:
    conds = [Task.org_id == org_id]
    if project_id:
        conds.append(Task.project_id == project_id)
    if assignee_id:
        conds.append(Task.assignee_user_id == assignee_id)
    if status:
        conds.append(Task.status == status)
    return list(db.scalars(select(Task).where(*conds).order_by(Task.created_at)))


def task_counts(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(Task.status, func.count())
        .where(Task.org_id == org_id, Task.project_id == project_id)
        .group_by(Task.status)
    ).all()
    return dict(rows)
