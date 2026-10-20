"""HTTP routes for projects, team, milestones and tasks."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db, set_org_context
from app.core.pagination import Page, PageDep
from app.core.permissions import Perm, Role, has_permission
from app.modules.identity.deps import require
from app.modules.identity.models import User
from app.modules.projects import queries, service
from app.modules.projects.schemas import (
    MemberAddRequest,
    MemberOut,
    MemberUpdateRequest,
    MilestoneCreateRequest,
    MilestoneOut,
    MilestoneUpdateRequest,
    ProjectCreateRequest,
    ProjectDetailOut,
    ProjectOut,
    ProjectStatusRequest,
    ProjectUpdateRequest,
    TaskCreateRequest,
    TaskOut,
    TaskUpdateRequest,
)

router = APIRouter(tags=["projects"])
Db = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(require(Perm.PROJECT_READ))]
Manager = Annotated[User, Depends(require(Perm.PROJECT_MANAGE))]
TaskEditor = Annotated[User, Depends(require(Perm.TASK_UPDATE))]


def _caller(user: User) -> service.Caller:
    return service.Caller(
        org_id=user.org_id, user_id=user.id, restricted=Role(user.role) == Role.TEAM_MEMBER
    )


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreateRequest, user: Manager, db: Db) -> ProjectOut:
    p = service.create_project(db, _caller(user), **body.model_dump())
    return ProjectOut.model_validate(p)


@router.get("/projects", response_model=Page[ProjectOut])
def list_projects(
    user: Reader,
    db: Db,
    page: PageDep,
    status: str | None = None,
    client_id: uuid.UUID | None = None,
) -> Page[ProjectOut]:
    set_org_context(db, user.org_id)
    c = _caller(user)
    items, total = queries.list_projects(
        db,
        user.org_id,
        user_id=user.id,
        restricted=c.restricted,
        status=status,
        client_id=client_id,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[ProjectOut.model_validate(i) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
def get_project(project_id: uuid.UUID, user: Reader, db: Db) -> ProjectDetailOut:
    c = _caller(user)
    set_org_context(db, user.org_id)
    project = queries.get_project(
        db, user.org_id, project_id, user_id=user.id, restricted=c.restricted
    )
    if project is None:
        from app.core.errors import NotFound

        raise NotFound("Project not found")
    return ProjectDetailOut(
        project=ProjectOut.model_validate(project),
        members=[
            MemberOut.model_validate(m) for m in queries.list_members(db, user.org_id, project_id)
        ],
        milestones=[
            MilestoneOut.model_validate(m)
            for m in queries.list_milestones(db, user.org_id, project_id)
        ],
        task_counts=queries.task_counts(db, user.org_id, project_id),
    )


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, body: ProjectUpdateRequest, user: Manager, db: Db
) -> ProjectOut:
    return ProjectOut.model_validate(
        service.update_project(db, _caller(user), project_id, **body.model_dump())
    )


@router.post("/projects/{project_id}/status", response_model=ProjectOut)
def change_status(
    project_id: uuid.UUID, body: ProjectStatusRequest, user: Manager, db: Db
) -> ProjectOut:
    return ProjectOut.model_validate(
        service.change_status(db, _caller(user), project_id, body.status)
    )


@router.post("/projects/{project_id}/members", response_model=MemberOut, status_code=201)
def add_member(project_id: uuid.UUID, body: MemberAddRequest, user: Manager, db: Db) -> MemberOut:
    m = service.add_member(
        db,
        _caller(user),
        project_id,
        user_id=body.user_id,
        hourly_rate_cents=body.hourly_rate_cents,
    )
    return MemberOut.model_validate(m)


@router.patch("/projects/{project_id}/members/{user_id}", response_model=MemberOut)
def update_member(
    project_id: uuid.UUID, user_id: uuid.UUID, body: MemberUpdateRequest, user: Manager, db: Db
) -> MemberOut:
    m = service.update_member(
        db, _caller(user), project_id, user_id, hourly_rate_cents=body.hourly_rate_cents
    )
    return MemberOut.model_validate(m)


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_member(project_id: uuid.UUID, user_id: uuid.UUID, user: Manager, db: Db) -> None:
    service.remove_member(db, _caller(user), project_id, user_id)


@router.post("/projects/{project_id}/milestones", response_model=MilestoneOut, status_code=201)
def create_milestone(
    project_id: uuid.UUID, body: MilestoneCreateRequest, user: Manager, db: Db
) -> MilestoneOut:
    return MilestoneOut.model_validate(
        service.create_milestone(db, _caller(user), project_id, **body.model_dump())
    )


@router.patch("/milestones/{milestone_id}", response_model=MilestoneOut)
def update_milestone(
    milestone_id: uuid.UUID, body: MilestoneUpdateRequest, user: Manager, db: Db
) -> MilestoneOut:
    return MilestoneOut.model_validate(
        service.update_milestone(db, _caller(user), milestone_id, **body.model_dump())
    )


@router.delete("/milestones/{milestone_id}", status_code=204)
def delete_milestone(milestone_id: uuid.UUID, user: Manager, db: Db) -> None:
    service.delete_milestone(db, _caller(user), milestone_id)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    project_id: uuid.UUID, user: Reader, db: Db, status: Annotated[str | None, Query()] = None
) -> list[TaskOut]:
    c = _caller(user)
    set_org_context(db, user.org_id)
    if (
        queries.get_project(db, user.org_id, project_id, user_id=user.id, restricted=c.restricted)
        is None
    ):
        from app.core.errors import NotFound

        raise NotFound("Project not found")
    return [
        TaskOut.model_validate(t)
        for t in queries.list_tasks(db, user.org_id, project_id=project_id, status=status)
    ]


@router.get("/tasks/mine", response_model=list[TaskOut])
def my_tasks(user: Reader, db: Db) -> list[TaskOut]:
    set_org_context(db, user.org_id)
    return [
        TaskOut.model_validate(t) for t in queries.list_tasks(db, user.org_id, assignee_id=user.id)
    ]


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(project_id: uuid.UUID, body: TaskCreateRequest, user: Manager, db: Db) -> TaskOut:
    return TaskOut.model_validate(
        service.create_task(db, _caller(user), project_id, **body.model_dump())
    )


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, body: TaskUpdateRequest, user: TaskEditor, db: Db) -> TaskOut:
    can_manage = has_permission(Role(user.role), Perm.PROJECT_MANAGE)
    t = service.update_task(db, _caller(user), task_id, can_manage=can_manage, **body.model_dump())
    return TaskOut.model_validate(t)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID, user: Manager, db: Db) -> None:
    service.delete_task(db, _caller(user), task_id)
