"""Project lifecycle state machine — pure functions, no I/O."""

STATUSES = ("planning", "active", "on_hold", "completed", "cancelled")
TERMINAL = frozenset({"completed", "cancelled"})
TASK_STATUSES = ("todo", "in_progress", "review", "done")
TASK_PRIORITIES = ("low", "medium", "high")

_ALLOWED: dict[str, frozenset[str]] = {
    "planning": frozenset({"active", "cancelled"}),
    "active": frozenset({"on_hold", "completed", "cancelled"}),
    "on_hold": frozenset({"active", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


def is_terminal(status: str) -> bool:
    return status in TERMINAL


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return False
    return to_status in _ALLOWED.get(from_status, frozenset())
