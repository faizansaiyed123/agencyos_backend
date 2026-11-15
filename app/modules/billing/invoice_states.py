"""Invoice lifecycle and the pure settlement calculation.

Credit notes reduce the receivable; refunds reverse cash actually received.
Those are separate immutable ledger entries and must never be conflated.
"""

STATUSES = ("draft", "sent", "partially_paid", "paid", "credited", "void")
_ALLOWED: dict[str, frozenset[str]] = {
    "draft": frozenset({"sent"}),
    "sent": frozenset({"partially_paid", "paid", "credited", "void"}),
    "partially_paid": frozenset({"sent", "partially_paid", "paid", "credited"}),
    "paid": frozenset({"sent", "partially_paid", "credited"}),
    "credited": frozenset(),
    "void": frozenset(),
}
PAYABLE = frozenset({"sent", "partially_paid"})


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in _ALLOWED.get(from_status, frozenset())


def is_final(status: str) -> bool:
    return status in {"paid", "credited", "void"}


def settlement(
    *,
    total_cents: int,
    amount_paid_cents: int,
    amount_refunded_cents: int = 0,
    credit_note_cents: int = 0,
) -> tuple[str, int, int]:
    """Return (status, amount_due, client_credit_balance), all in cents.

    amount_paid is gross cash received; amount_refunded is cash returned.
    credit_note is the amount by which the original invoice receivable was reduced.
    A client credit balance is exposed separately instead of returning a negative
    invoice balance when credits/refunds exceed the remaining receivable.
    """
    net_total = total_cents - credit_note_cents
    net_received = amount_paid_cents - amount_refunded_cents
    net_position = net_total - net_received

    amount_due = max(net_position, 0)
    client_credit_balance = max(-net_position, 0)

    if credit_note_cents == total_cents:
        status = "credited"
    elif net_received >= net_total:
        status = "paid"
    elif net_received > 0:
        status = "partially_paid"
    else:
        status = "sent"

    return status, amount_due, client_credit_balance
