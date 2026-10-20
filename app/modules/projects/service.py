"""Projects business logic: projects, team, milestones, tasks."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import set_org_context
from app.core.errors import BusinessRuleViolation, Conflict, Forbidden, NotFound
from app.modules.crm import queries as crm_queries
from app.modules.identity.models import User
from app.modules.projects import queries
from app.modules.projects.models import Milestone, Project, ProjectMember, Task
from app.modules.projects.project_states import can_transition, is_terminal
from app.platform import events
from app.platform.audit import record_audit
from app.platform.notifications import notify


@dataclass(frozen=True)
class Caller:
    org_id: uuid.UUID
    user_id: uuid.UUID
    restricted: bool  # team members only see/touch what they're assigned to


def _project(db: Session, c: Caller, project_id: uuid.UUID) -> Project:
    set_org_context(db, c.org_id)
    project = queries.get_project(
        db, c.org_id, project_id, user_id=c.user_id, restricted=c.restricted
    )
    if project is None:
        raise NotFound("Project not found")
    return project


def _open_project(db: Session, c: Caller, project_id: uuid.UUID) -> Project:
    project = _project(db, c, project_id)
    if is_terminal(project.status):
        raise Conflict(f"Project is {project.status}", code="project_closed")
    return project


def _require_user(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.org_id != org_id or not user.is_active:
        raise BusinessRuleViolation("User not found in this organization", code="user_not_found")
    return user


def create_project(
    db: Session,
    c: Caller,
    *,
    client_id: uuid.UUID,
    name: str,
    description: str | None,
    budget_amount: int | None,
    currency: str,
    start_date: date | None,
    due_date: date | None,
    manager_user_id: uuid.UUID | None,
) -> Project:
    set_org_context(db, c.org_id)
    client = crm_queries.get_client(db, c.org_id, client_id)
    if client is None:
        raise NotFound("Client not found")
    if client.archived_at is not None:
        raise Conflict("Cannot create a project for an archived client", code="client_archived")
    manager = manager_user_id or c.user_id
    _require_user(db, c.org_id, manager)
    project = Project(
        org_id=c.org_id,
        client_id=client_id,
        name=name,
        description=description,
        budget_amount=budget_amount,
        currency=currency.upper(),
        start_date=start_date,
        due_date=due_date,
        manager_user_id=manager,
        created_by=c.user_id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(org_id=c.org_id, project_id=project.id, user_id=manager))
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
        data={"name": name},
    )
    events.emit(
        db,
        org_id=c.org_id,
        event_type="project.created",
        data={"project_id": str(project.id), "name": name},
    )
    db.commit()
    return project


def create_project_from_deal(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    deal_id: uuid.UUID,
    client_id: uuid.UUID,
    proposal_id: uuid.UUID,
    name: str,
    budget_amount: int,
    currency: str,
    milestones: list[tuple[str, int]],
    manager_user_id: uuid.UUID,
) -> tuple[Project, bool]:
    """Idempotent: converting the same deal twice returns the existing project.
    Flushes but never commits — it runs inside the caller's transaction so the
    proposal acceptance and the project creation succeed or fail together."""
    set_org_context(db, org_id)
    existing = queries.get_project_for_deal(db, org_id, deal_id)
    if existing is not None:
        return existing, False
    project = Project(
        org_id=org_id,
        client_id=client_id,
        deal_id=deal_id,
        proposal_id=proposal_id,
        name=name,
        budget_amount=budget_amount,
        currency=currency,
        manager_user_id=manager_user_id,
        created_by=actor_id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(org_id=org_id, project_id=project.id, user_id=manager_user_id))
    for position, (m_name, amount) in enumerate(milestones):
        db.add(
            Milestone(
                org_id=org_id,
                project_id=project.id,
                name=m_name,
                amount_cents=amount,
                position=position,
            )
        )
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="project.created_from_deal",
        entity_type="project",
        entity_id=project.id,
        data={"deal_id": str(deal_id), "budget": budget_amount},
    )
    events.emit(
        db,
        org_id=org_id,
        event_type="project.created",
        data={"project_id": str(project.id), "name": name},
    )
    db.flush()
    return project, True


def update_project(
    db: Session,
    c: Caller,
    project_id: uuid.UUID,
    *,
    name: str | None,
    description: str | None,
    budget_amount: int | None,
    start_date: date | None,
    due_date: date | None,
    manager_user_id: uuid.UUID | None,
) -> Project:
    project = _open_project(db, c, project_id)
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    if budget_amount is not None:
        project.budget_amount = budget_amount
    if start_date is not None:
        project.start_date = start_date
    if due_date is not None:
        project.due_date = due_date
    if manager_user_id is not None and manager_user_id != project.manager_user_id:
        _require_user(db, c.org_id, manager_user_id)
        if queries.get_member(db, c.org_id, project.id, manager_user_id) is None:
            db.add(ProjectMember(org_id=c.org_id, project_id=project.id, user_id=manager_user_id))
        project.manager_user_id = manager_user_id
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="project.updated",
        entity_type="project",
        entity_id=project.id,
    )
    db.commit()
    return project


def change_status(db: Session, c: Caller, project_id: uuid.UUID, to_status: str) -> Project:
    project = _project(db, c, project_id)
    if not can_transition(project.status, to_status):
        raise Conflict(
            f"Cannot move a project from '{project.status}' to '{to_status}'",
            code="invalid_status_transition",
        )
    if to_status == "completed":
        open_tasks = [
            t for t in queries.list_tasks(db, c.org_id, project_id=project.id) if t.status != "done"
        ]
        if open_tasks:
            raise BusinessRuleViolation(
                f"{len(open_tasks)} task(s) are not done yet", code="open_tasks_remain"
            )
    previous = project.status
    project.status = to_status
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="project.status_changed",
        entity_type="project",
        entity_id=project.id,
        data={"from": previous, "to": to_status},
    )
    events.emit(
        db,
        org_id=c.org_id,
        event_type=f"project.{to_status}",
        data={"project_id": str(project.id), "from": previous, "to": to_status},
    )
    db.commit()
    return project


# --- team -------------------------------------------------------------------------


def add_member(
    db: Session,
    c: Caller,
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    hourly_rate_cents: int | None,
) -> ProjectMember:
    project = _open_project(db, c, project_id)
    _require_user(db, c.org_id, user_id)
    if queries.get_member(db, c.org_id, project.id, user_id) is not None:
        raise Conflict("User is already on this project", code="already_member")
    member = ProjectMember(
        org_id=c.org_id, project_id=project.id, user_id=user_id, hourly_rate_cents=hourly_rate_cents
    )
    db.add(member)
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="project.member_added",
        entity_type="project",
        entity_id=project.id,
        data={"user_id": str(user_id)},
    )
    db.commit()
    return member


def update_member(
    db: Session,
    c: Caller,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    hourly_rate_cents: int | None,
) -> ProjectMember:
    project = _open_project(db, c, project_id)
    member = queries.get_member(db, c.org_id, project.id, user_id)
    if member is None:
        raise NotFound("Member not found")
    member.hourly_rate_cents = hourly_rate_cents
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="project.member_rate_changed",
        entity_type="project",
        entity_id=project.id,
        data={"user_id": str(user_id), "rate": hourly_rate_cents},
    )
    db.commit()
    return member


def remove_member(db: Session, c: Caller, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    project = _open_project(db, c, project_id)
    member = queries.get_member(db, c.org_id, project.id, user_id)
    if member is None:
        raise NotFound("Member not found")
    if user_id == project.manager_user_id:
        raise BusinessRuleViolation(
            "Reassign the project manager first", code="cannot_remove_manager"
        )
    db.execute(
        update(Task)
        .where(
            Task.org_id == c.org_id,
            Task.project_id == project.id,
            Task.assignee_user_id == user_id,
            Task.status != "done",
        )
        .values(assignee_user_id=None)
    )
    db.delete(member)
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="project.member_removed",
        entity_type="project",
        entity_id=project.id,
        data={"user_id": str(user_id)},
    )
    db.commit()


# --- milestones ---------------------------------------------------------------------


def create_milestone(
    db: Session,
    c: Caller,
    project_id: uuid.UUID,
    *,
    name: str,
    due_date: date | None,
    amount_cents: int | None,
    position: int,
) -> Milestone:
    project = _open_project(db, c, project_id)
    m = Milestone(
        org_id=c.org_id,
        project_id=project.id,
        name=name,
        due_date=due_date,
        amount_cents=amount_cents,
        position=position,
    )
    db.add(m)
    db.flush()
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="milestone.created",
        entity_type="milestone",
        entity_id=m.id,
        data={"project_id": str(project.id)},
    )
    db.commit()
    return m


def update_milestone(
    db: Session,
    c: Caller,
    milestone_id: uuid.UUID,
    *,
    name: str | None,
    due_date: date | None,
    amount_cents: int | None,
    position: int | None,
    done: bool | None,
) -> Milestone:
    set_org_context(db, c.org_id)
    m = queries.get_milestone(db, c.org_id, milestone_id)
    if m is None:
        raise NotFound("Milestone not found")
    _open_project(db, c, m.project_id)
    if name is not None:
        m.name = name
    if due_date is not None:
        m.due_date = due_date
    if amount_cents is not None:
        m.amount_cents = amount_cents
    if position is not None:
        m.position = position
    if done is not None:
        m.status = "done" if done else "pending"
        m.completed_at = utcnow() if done else None
        if done:
            events.emit(
                db,
                org_id=c.org_id,
                event_type="milestone.completed",
                data={"milestone_id": str(m.id), "project_id": str(m.project_id)},
            )
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="milestone.updated",
        entity_type="milestone",
        entity_id=m.id,
    )
    db.commit()
    return m


def delete_milestone(db: Session, c: Caller, milestone_id: uuid.UUID) -> None:
    set_org_context(db, c.org_id)
    m = queries.get_milestone(db, c.org_id, milestone_id)
    if m is None:
        raise NotFound("Milestone not found")
    _open_project(db, c, m.project_id)
    db.delete(m)
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="milestone.deleted",
        entity_type="milestone",
        entity_id=m.id,
    )
    db.commit()


# --- tasks --------------------------------------------------------------------------


def _check_assignee(db: Session, c: Caller, project_id: uuid.UUID, assignee: uuid.UUID) -> None:
    if queries.get_member(db, c.org_id, project_id, assignee) is None:
        raise BusinessRuleViolation(
            "Assignee must be on the project team", code="assignee_not_member"
        )


def _check_milestone(
    db: Session, c: Caller, project_id: uuid.UUID, milestone_id: uuid.UUID
) -> None:
    m = queries.get_milestone(db, c.org_id, milestone_id)
    if m is None or m.project_id != project_id:
        raise BusinessRuleViolation(
            "Milestone is not part of this project", code="milestone_mismatch"
        )


def create_task(
    db: Session,
    c: Caller,
    project_id: uuid.UUID,
    *,
    title: str,
    description: str | None,
    milestone_id: uuid.UUID | None,
    assignee_user_id: uuid.UUID | None,
    priority: str,
    due_date: date | None,
    estimate_minutes: int | None,
) -> Task:
    project = _open_project(db, c, project_id)
    if assignee_user_id:
        _check_assignee(db, c, project.id, assignee_user_id)
    if milestone_id:
        _check_milestone(db, c, project.id, milestone_id)
    task = Task(
        org_id=c.org_id,
        project_id=project.id,
        title=title,
        description=description,
        milestone_id=milestone_id,
        assignee_user_id=assignee_user_id,
        priority=priority,
        due_date=due_date,
        estimate_minutes=estimate_minutes,
        created_by=c.user_id,
    )
    db.add(task)
    db.flush()
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
        data={"project_id": str(project.id), "title": title},
    )
    if assignee_user_id:
        events.emit(
            db,
            org_id=c.org_id,
            event_type="task.assigned",
            data={"task_id": str(task.id), "assignee": str(assignee_user_id), "title": title},
        )
        if assignee_user_id != c.user_id:
            notify(
                db,
                org_id=c.org_id,
                user_id=assignee_user_id,
                kind="task_assigned",
                title=f"New task: {title}",
                entity_type="task",
                entity_id=task.id,
            )
    db.commit()
    return task


def update_task(  # noqa: C901, PLR0912
    db: Session,
    c: Caller,
    task_id: uuid.UUID,
    *,
    title: str | None,
    description: str | None,
    milestone_id: uuid.UUID | None,
    assignee_user_id: uuid.UUID | None,
    unassign: bool,
    status: str | None,
    priority: str | None,
    due_date: date | None,
    estimate_minutes: int | None,
    can_manage: bool,
) -> Task:
    set_org_context(db, c.org_id)
    task = queries.get_task(db, c.org_id, task_id)
    if task is None:
        raise NotFound("Task not found")
    project = _open_project(db, c, task.project_id)

    structural = (
        any(
            v is not None
            for v in (
                title,
                description,
                milestone_id,
                assignee_user_id,
                priority,
                due_date,
                estimate_minutes,
            )
        )
        or unassign
    )
    if structural and not can_manage:
        raise Forbidden("Only project managers can edit task details; you can change its status")
    if not can_manage and task.assignee_user_id != c.user_id:
        raise Forbidden("You can only update tasks assigned to you")

    if title is not None:
        task.title = title
    if description is not None:
        task.description = description
    if priority is not None:
        task.priority = priority
    if due_date is not None:
        task.due_date = due_date
    if estimate_minutes is not None:
        task.estimate_minutes = estimate_minutes
    if milestone_id is not None:
        _check_milestone(db, c, project.id, milestone_id)
        task.milestone_id = milestone_id
    if unassign:
        task.assignee_user_id = None
    elif assignee_user_id is not None and assignee_user_id != task.assignee_user_id:
        _check_assignee(db, c, project.id, assignee_user_id)
        task.assignee_user_id = assignee_user_id
        events.emit(
            db,
            org_id=c.org_id,
            event_type="task.assigned",
            data={"task_id": str(task.id), "assignee": str(assignee_user_id), "title": task.title},
        )
        if assignee_user_id != c.user_id:
            notify(
                db,
                org_id=c.org_id,
                user_id=assignee_user_id,
                kind="task_assigned",
                title=f"Task assigned to you: {task.title}",
                entity_type="task",
                entity_id=task.id,
            )
    if status is not None and status != task.status:
        task.status = status
        task.completed_at = utcnow() if status == "done" else None
        if status == "done":
            events.emit(
                db,
                org_id=c.org_id,
                event_type="task.completed",
                data={"task_id": str(task.id), "project_id": str(project.id)},
            )
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="task.updated",
        entity_type="task",
        entity_id=task.id,
    )
    db.commit()
    return task


def delete_task(db: Session, c: Caller, task_id: uuid.UUID) -> None:
    set_org_context(db, c.org_id)
    task = queries.get_task(db, c.org_id, task_id)
    if task is None:
        raise NotFound("Task not found")
    _open_project(db, c, task.project_id)
    db.delete(task)
    record_audit(
        db,
        org_id=c.org_id,
        actor_user_id=c.user_id,
        action="task.deleted",
        entity_type="task",
        entity_id=task.id,
    )
    db.commit()
