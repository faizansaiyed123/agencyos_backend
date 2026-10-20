"""The proposal state machine — pure functions, same pattern as
app.modules.crm.deal_states. A proposal is only editable (items can be
added/changed/removed) while in 'draft'; sending, accepting, rejecting and
expiring are all one-way moves.
"""

STATUSES = ("draft", "sent", "accepted", "rejected", "expired")
TERMINAL_STATUSES = frozenset({"accepted", "rejected", "expired"})

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"sent"}),
    "sent": frozenset({"accepted", "rejected", "expired"}),
    "accepted": frozenset(),
    "rejected": frozenset(),
    "expired": frozenset(),
}


def is_valid_status(status: str) -> bool:
    return status in STATUSES


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def is_editable(status: str) -> bool:
    """Line items may only be added/changed/removed while the proposal is
    still a draft — once sent, the client may be looking at that exact
    version, so it must not change under them."""
    return status == "draft"


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return False
    return to_status in _ALLOWED_TRANSITIONS.get(from_status, frozenset())
