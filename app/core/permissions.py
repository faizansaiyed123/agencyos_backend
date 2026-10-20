"""Roles and the permission matrix.

The whole authorization model is this one file so it can be reviewed at a glance and
unit-tested. Route-level checks use `require(permission)` (see app.core.auth);
object-level scoping (e.g. a team member only sees their own projects) is done in
each module's queries.
"""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ACCOUNT_MANAGER = "account_manager"
    PROJECT_MANAGER = "project_manager"
    TEAM_MEMBER = "team_member"
    FINANCE = "finance"
    CLIENT = "client"  # external client-portal user


STAFF_ROLES = frozenset(Role) - {Role.CLIENT}
ROLE_VALUES = tuple(r.value for r in Role)


class Perm(StrEnum):
    USER_READ = "user:read"
    USER_INVITE = "user:invite"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"
    CLIENT_READ = "client:read"
    CLIENT_MANAGE = "client:manage"
    DEAL_READ = "deal:read"
    DEAL_MANAGE = "deal:manage"
    PROPOSAL_READ = "proposal:read"
    PROPOSAL_MANAGE = "proposal:manage"
    PROJECT_READ = "project:read"
    PROJECT_MANAGE = "project:manage"
    TASK_UPDATE = "task:update"
    TIME_LOG = "time:log"
    TIME_READ_ALL = "time:read_all"
    TIME_APPROVE = "time:approve"
    INVOICE_READ = "invoice:read"
    INVOICE_MANAGE = "invoice:manage"
    COMMENT_WRITE = "comment:write"
    APPROVAL_MANAGE = "approval:manage"
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    REPORT_READ = "report:read"
    WEBHOOK_MANAGE = "webhook:manage"
    FLAG_MANAGE = "flag:manage"
    PRIVACY_MANAGE = "privacy:manage"


_ALL = frozenset(Perm)

_COLLAB = {Perm.COMMENT_WRITE, Perm.FILE_READ, Perm.FILE_WRITE}

PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.OWNER: _ALL,
    Role.ADMIN: _ALL,
    Role.ACCOUNT_MANAGER: frozenset(
        {
            Perm.USER_READ, Perm.CLIENT_READ, Perm.CLIENT_MANAGE, Perm.DEAL_READ,
            Perm.DEAL_MANAGE, Perm.PROPOSAL_READ, Perm.PROPOSAL_MANAGE, Perm.PROJECT_READ,
            Perm.INVOICE_READ, Perm.REPORT_READ, Perm.TIME_LOG, Perm.APPROVAL_MANAGE,
            *_COLLAB,
        }
    ),
    Role.PROJECT_MANAGER: frozenset(
        {
            Perm.USER_READ, Perm.CLIENT_READ, Perm.DEAL_READ, Perm.PROPOSAL_READ,
            Perm.PROJECT_READ, Perm.PROJECT_MANAGE, Perm.TASK_UPDATE, Perm.TIME_LOG,
            Perm.TIME_READ_ALL, Perm.TIME_APPROVE, Perm.REPORT_READ, Perm.APPROVAL_MANAGE,
            *_COLLAB,
        }
    ),
    Role.TEAM_MEMBER: frozenset(
        {Perm.USER_READ, Perm.CLIENT_READ, Perm.PROJECT_READ, Perm.TASK_UPDATE, Perm.TIME_LOG,
         *_COLLAB}
    ),
    Role.FINANCE: frozenset(
        {
            Perm.USER_READ, Perm.CLIENT_READ, Perm.DEAL_READ, Perm.PROPOSAL_READ,
            Perm.PROJECT_READ, Perm.TIME_READ_ALL, Perm.TIME_APPROVE, Perm.INVOICE_READ,
            Perm.INVOICE_MANAGE, Perm.REPORT_READ, Perm.COMMENT_WRITE, Perm.FILE_READ,
        }
    ),
    Role.CLIENT: frozenset(),
}  # fmt: skip


def has_permission(role: Role, perm: Perm) -> bool:
    return perm in PERMISSIONS[role]
