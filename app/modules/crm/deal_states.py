"""The deal pipeline state machine — pure functions, no I/O, exhaustively unit
tested in isolation from the database. This is the one source of truth for
which stage transitions are legal; the service layer and the DB CHECK
constraint both derive from the same STAGES list.
"""

STAGES = ("lead", "qualified", "proposal_sent", "negotiation", "won", "lost")
# The linear happy-path order (excludes the 'lost' branch), used when some
# other event (e.g. an accepted proposal) is authoritative evidence that a
# deal reached 'won' regardless of which intermediate stage it was sitting
# at — see app.modules.proposals.service.accept_proposal, which walks a deal
# forward one stage at a time along this order so every individual
# transition is still validated and recorded in history, rather than
# fabricating a single lead-straight-to-won jump the state machine forbids.
HAPPY_PATH_ORDER = ("lead", "qualified", "proposal_sent", "negotiation", "won")
TERMINAL_STAGES = frozenset({"won", "lost"})

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "lead": frozenset({"qualified", "lost"}),
    "qualified": frozenset({"proposal_sent", "lost"}),
    "proposal_sent": frozenset({"negotiation", "lost"}),
    "negotiation": frozenset({"won", "lost"}),
    "won": frozenset(),
    "lost": frozenset(),
}


def is_valid_stage(stage: str) -> bool:
    return stage in STAGES


def is_terminal(stage: str) -> bool:
    return stage in TERMINAL_STAGES


def can_transition(from_stage: str, to_stage: str) -> bool:
    """A no-op 'transition' (from_stage == to_stage) is never valid — callers
    that don't actually want to change anything shouldn't call transition
    logic at all. Every real transition must move strictly forward or to a
    terminal stage; there is no going backward."""
    if from_stage == to_stage:
        return False
    return to_stage in _ALLOWED_TRANSITIONS.get(from_stage, frozenset())
