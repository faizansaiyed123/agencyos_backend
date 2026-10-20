"""Invoice lifecycle — pure functions. 'overdue' is derived from due_date, never stored."""

STATUSES = ("draft", "sent", "partially_paid", "paid", "void")
_ALLOWED: dict[str, frozenset[str]] = {
    "draft": frozenset({"sent"}),
    "sent": frozenset({"partially_paid", "paid", "void"}),
    "partially_paid": frozenset({"partially_paid", "paid"}),
    "paid": frozenset(),
    "void": frozenset(),
}
PAYABLE = frozenset({"sent", "partially_paid"})


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in _ALLOWED.get(from_status, frozenset())


def is_final(status: str) -> bool:
    return status in {"paid", "void"}
