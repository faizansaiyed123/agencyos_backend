"""Billing business logic. Every function sets RLS context, writes an audit row and
commits exactly once, so each operation is atomic."""

import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import set_org_context
from app.core.errors import BusinessRuleViolation, Conflict, NotFound
from app.modules.billing.invoice_states import PAYABLE
from app.modules.billing.models import Invoice, InvoiceLine, Payment
from app.modules.crm import queries as crm_queries
from app.modules.identity.models import User
from app.modules.projects import queries as project_queries
from app.modules.time.models import TimeEntry, amount_cents
from app.platform import events
from app.platform.audit import record_audit

DEFAULT_TERMS_DAYS = 30


def _cents(qty: Decimal, unit_cents: int) -> int:
    return int((qty * unit_cents).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _tax(subtotal: int, bps: int) -> int:
    return (subtotal * bps + 5000) // 10000


def balance(inv: Invoice) -> int:
    return inv.total_cents - inv.amount_paid_cents


def is_overdue(inv: Invoice, today: date | None = None) -> bool:
    return (
        inv.status in PAYABLE
        and inv.due_date is not None
        and inv.due_date < (today or utcnow().date())
    )


def get_invoice(
    db: Session, org_id: uuid.UUID, invoice_id: uuid.UUID, *, lock: bool = False
) -> Invoice:
    set_org_context(db, org_id)
    stmt = select(Invoice).where(Invoice.org_id == org_id, Invoice.id == invoice_id)
    if lock:
        stmt = stmt.with_for_update()
    inv = db.scalar(stmt)
    if inv is None:
        raise NotFound("Invoice not found")
    return inv


def _draft(db: Session, org_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    inv = get_invoice(db, org_id, invoice_id, lock=True)
    if inv.status != "draft":
        raise Conflict(
            f"Invoice is {inv.status}; only drafts can be edited", code="invoice_not_draft"
        )
    return inv


def lines_of(db: Session, org_id: uuid.UUID, invoice_id: uuid.UUID) -> list[InvoiceLine]:
    return list(
        db.scalars(
            select(InvoiceLine)
            .where(InvoiceLine.org_id == org_id, InvoiceLine.invoice_id == invoice_id)
            .order_by(InvoiceLine.position, InvoiceLine.created_at)
        )
    )


def payments_of(db: Session, org_id: uuid.UUID, invoice_id: uuid.UUID) -> list[Payment]:
    return list(
        db.scalars(
            select(Payment)
            .where(Payment.org_id == org_id, Payment.invoice_id == invoice_id)
            .order_by(Payment.created_at)
        )
    )


def _recalc(db: Session, inv: Invoice) -> None:
    db.flush()
    inv.subtotal_cents = sum(line.amount_cents for line in lines_of(db, inv.org_id, inv.id))
    inv.tax_cents = _tax(inv.subtotal_cents, inv.tax_rate_bps)
    inv.total_cents = inv.subtotal_cents + inv.tax_cents


def create_invoice(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    client_id: uuid.UUID,
    project_id: uuid.UUID | None,
    currency: str,
    due_date: date | None,
    tax_rate_bps: int,
    notes: str | None,
) -> Invoice:
    set_org_context(db, org_id)
    client = crm_queries.get_client(db, org_id, client_id)
    if client is None:
        raise NotFound("Client not found")
    if project_id is not None:
        project = project_queries.get_project(
            db, org_id, project_id, user_id=actor_id, restricted=False
        )
        if project is None:
            raise NotFound("Project not found")
        if project.client_id != client_id:
            raise BusinessRuleViolation(
                "Project belongs to a different client", code="client_project_mismatch"
            )
        currency = project.currency
    inv = Invoice(
        org_id=org_id,
        client_id=client_id,
        project_id=project_id,
        currency=currency.upper(),
        due_date=due_date,
        tax_rate_bps=tax_rate_bps,
        notes=notes,
        created_by=actor_id,
    )
    db.add(inv)
    db.flush()
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.created",
        entity_type="invoice",
        entity_id=inv.id,
        data={"client_id": str(client_id)},
    )
    events.emit(db, org_id=org_id, event_type="invoice.created", data={"invoice_id": str(inv.id)})
    db.commit()
    return inv


def update_invoice(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    due_date: date | None,
    tax_rate_bps: int | None,
    notes: str | None,
) -> Invoice:
    inv = _draft(db, org_id, invoice_id)
    if due_date is not None:
        inv.due_date = due_date
    if notes is not None:
        inv.notes = notes
    if tax_rate_bps is not None:
        inv.tax_rate_bps = tax_rate_bps
        _recalc(db, inv)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.updated",
        entity_type="invoice",
        entity_id=inv.id,
    )
    db.commit()
    return inv


def _next_position(db: Session, inv: Invoice) -> int:
    return len(lines_of(db, inv.org_id, inv.id))


def add_line(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    description: str,
    quantity: Decimal,
    unit_cents: int,
) -> InvoiceLine:
    inv = _draft(db, org_id, invoice_id)
    line = InvoiceLine(
        org_id=org_id,
        invoice_id=inv.id,
        description=description,
        quantity=quantity,
        unit_cents=unit_cents,
        amount_cents=_cents(quantity, unit_cents),
        position=_next_position(db, inv),
    )
    db.add(line)
    _recalc(db, inv)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.line_added",
        entity_type="invoice",
        entity_id=inv.id,
        data={"amount": line.amount_cents},
    )
    db.commit()
    return line


def add_milestone_line(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    milestone_id: uuid.UUID,
) -> InvoiceLine:
    inv = _draft(db, org_id, invoice_id)
    m = project_queries.get_milestone(db, org_id, milestone_id)
    if m is None or inv.project_id is None or m.project_id != inv.project_id:
        raise BusinessRuleViolation(
            "Milestone is not part of this invoice's project", code="milestone_mismatch"
        )
    if not m.amount_cents:
        raise BusinessRuleViolation(
            "Milestone has no billable amount", code="milestone_not_billable"
        )
    already = db.scalar(
        select(InvoiceLine.id)
        .join(
            Invoice, (Invoice.org_id == InvoiceLine.org_id) & (Invoice.id == InvoiceLine.invoice_id)
        )
        .where(
            InvoiceLine.org_id == org_id,
            InvoiceLine.milestone_id == milestone_id,
            Invoice.status != "void",
        )
    )
    if already is not None:
        raise Conflict("Milestone has already been invoiced", code="milestone_already_invoiced")
    line = InvoiceLine(
        org_id=org_id,
        invoice_id=inv.id,
        description=m.name,
        quantity=Decimal(1),
        unit_cents=m.amount_cents,
        amount_cents=m.amount_cents,
        milestone_id=m.id,
        position=_next_position(db, inv),
    )
    db.add(line)
    _recalc(db, inv)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.milestone_billed",
        entity_type="invoice",
        entity_id=inv.id,
        data={"milestone_id": str(m.id)},
    )
    db.commit()
    return line


def unbilled_entries(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> list[TimeEntry]:
    set_org_context(db, org_id)
    return list(
        db.scalars(
            select(TimeEntry)
            .where(
                TimeEntry.org_id == org_id,
                TimeEntry.project_id == project_id,
                TimeEntry.status == "approved",
                TimeEntry.billable.is_(True),
                TimeEntry.invoice_id.is_(None),
            )
            .order_by(TimeEntry.entry_date)
        )
    )


def add_time_lines(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    entry_ids: list[uuid.UUID] | None,
) -> list[InvoiceLine]:
    inv = _draft(db, org_id, invoice_id)
    if inv.project_id is None:
        raise BusinessRuleViolation(
            "Time can only be billed on a project invoice", code="no_project"
        )
    entries = unbilled_entries(db, org_id, inv.project_id)
    if entry_ids is not None:
        wanted = set(entry_ids)
        entries = [e for e in entries if e.id in wanted]
        if len(entries) != len(wanted):
            raise BusinessRuleViolation(
                "Some entries are not approved, billable and unbilled", code="entries_not_billable"
            )
    if not entries:
        raise BusinessRuleViolation(
            "There is no approved unbilled time to invoice", code="nothing_to_bill"
        )

    groups: dict[tuple[uuid.UUID, int], list[TimeEntry]] = {}
    for e in entries:
        groups.setdefault((e.user_id, e.rate_cents or 0), []).append(e)
    created: list[InvoiceLine] = []
    for (user_id, rate), items in groups.items():
        user = db.get(User, user_id)
        minutes = sum(e.minutes for e in items)
        amount = sum(amount_cents(e.minutes, e.rate_cents) for e in items)
        line = InvoiceLine(
            org_id=org_id,
            invoice_id=inv.id,
            description=f"Time — {user.full_name if user else 'team'}",
            quantity=(Decimal(minutes) / 60).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            or Decimal("0.01"),
            unit_cents=rate,
            amount_cents=amount,
            position=_next_position(db, inv) + len(created),
            time_entry_ids=[str(e.id) for e in items],
        )
        db.add(line)
        created.append(line)
        for e in items:
            e.status = "invoiced"
            e.invoice_id = inv.id
    _recalc(db, inv)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.time_billed",
        entity_type="invoice",
        entity_id=inv.id,
        data={"entries": len(entries)},
    )
    db.commit()
    return created


def _release_entries(db: Session, org_id: uuid.UUID, entry_ids: list[Any]) -> None:
    if entry_ids:
        db.execute(
            update(TimeEntry)
            .where(
                TimeEntry.org_id == org_id, TimeEntry.id.in_([uuid.UUID(str(i)) for i in entry_ids])
            )
            .values(status="approved", invoice_id=None)
        )


def remove_line(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> None:
    inv = _draft(db, org_id, invoice_id)
    line = db.scalar(
        select(InvoiceLine).where(
            InvoiceLine.org_id == org_id,
            InvoiceLine.id == line_id,
            InvoiceLine.invoice_id == inv.id,
        )
    )
    if line is None:
        raise NotFound("Line not found")
    _release_entries(db, org_id, line.time_entry_ids)
    db.delete(line)
    _recalc(db, inv)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.line_removed",
        entity_type="invoice",
        entity_id=inv.id,
    )
    db.commit()


def delete_draft(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, invoice_id: uuid.UUID
) -> None:
    inv = _draft(db, org_id, invoice_id)
    for line in lines_of(db, org_id, inv.id):
        _release_entries(db, org_id, line.time_entry_ids)
    db.flush()
    db.delete(inv)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.draft_deleted",
        entity_type="invoice",
        entity_id=inv.id,
    )
    db.commit()


def _next_number(db: Session, org_id: uuid.UUID, year: int) -> str:
    n = db.execute(
        text(
            "INSERT INTO invoice_counters (org_id, year, last_number) VALUES (:o, :y, 1) "
            "ON CONFLICT (org_id, year) DO UPDATE "
            "SET last_number = invoice_counters.last_number + 1 "
            "RETURNING last_number"
        ),
        {"o": org_id, "y": year},
    ).scalar_one()
    return f"INV-{year}-{n:04d}"


def issue_invoice(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, invoice_id: uuid.UUID
) -> Invoice:
    inv = _draft(db, org_id, invoice_id)
    if not lines_of(db, org_id, inv.id) or inv.total_cents <= 0:
        raise BusinessRuleViolation(
            "Add at least one priced line before issuing", code="invoice_empty"
        )
    today = utcnow().date()
    inv.number = _next_number(db, org_id, today.year)
    inv.status = "sent"
    inv.issue_date = today
    inv.due_date = inv.due_date or today + timedelta(days=DEFAULT_TERMS_DAYS)
    if inv.due_date < today:
        raise BusinessRuleViolation("Due date cannot be in the past", code="due_date_past")
    inv.sent_at = utcnow()
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.issued",
        entity_type="invoice",
        entity_id=inv.id,
        data={"number": inv.number, "total": inv.total_cents},
    )
    events.emit(
        db,
        org_id=org_id,
        event_type="invoice.sent",
        data={"invoice_id": str(inv.id), "number": inv.number, "total_cents": inv.total_cents},
    )
    db.commit()
    return inv


def record_payment(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    amount_cents_: int,
    paid_on: date | None,
    method: str,
    reference: str | None,
    commit: bool = True,
) -> tuple[Invoice, Payment]:
    inv = get_invoice(db, org_id, invoice_id, lock=True)  # row lock: concurrent payments serialise
    if inv.status not in PAYABLE:
        raise Conflict(
            f"Cannot record a payment on a {inv.status} invoice", code="invoice_not_payable"
        )
    if amount_cents_ > balance(inv):
        raise BusinessRuleViolation(
            f"Payment exceeds the outstanding balance of {balance(inv)} cents", code="overpayment"
        )
    payment = Payment(
        org_id=org_id,
        invoice_id=inv.id,
        amount_cents=amount_cents_,
        paid_on=paid_on or utcnow().date(),
        method=method,
        reference=reference,
        created_by=actor_id,
    )
    db.add(payment)
    inv.amount_paid_cents += amount_cents_
    settled = inv.amount_paid_cents == inv.total_cents
    inv.status = "paid" if settled else "partially_paid"
    if settled:
        inv.paid_at = utcnow()
    db.flush()
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="payment.recorded",
        entity_type="invoice",
        entity_id=inv.id,
        data={"amount": amount_cents_, "settled": settled},
    )
    events.emit(
        db,
        org_id=org_id,
        event_type="payment.recorded",
        data={"invoice_id": str(inv.id), "amount_cents": amount_cents_},
    )
    if settled:
        events.emit(
            db,
            org_id=org_id,
            event_type="invoice.paid",
            data={"invoice_id": str(inv.id), "number": inv.number},
        )
    if commit:
        db.commit()
    return inv, payment


def void_invoice(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, invoice_id: uuid.UUID, reason: str
) -> Invoice:
    inv = get_invoice(db, org_id, invoice_id, lock=True)
    if inv.status == "draft":
        raise Conflict("Discard a draft instead of voiding it", code="invoice_is_draft")
    if inv.status != "sent":
        raise Conflict(
            "Only an issued invoice with no payments can be voided",
            code="invoice_has_payments" if inv.amount_paid_cents else "invoice_not_voidable",
        )
    for line in lines_of(db, org_id, inv.id):
        _release_entries(db, org_id, line.time_entry_ids)
    inv.status = "void"
    inv.voided_at = utcnow()
    inv.void_reason = reason
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="invoice.voided",
        entity_type="invoice",
        entity_id=inv.id,
        data={"number": inv.number, "reason": reason},
    )
    events.emit(
        db,
        org_id=org_id,
        event_type="invoice.voided",
        data={"invoice_id": str(inv.id), "number": inv.number},
    )
    db.commit()
    return inv


def list_invoices(
    db: Session,
    *,
    org_id: uuid.UUID,
    status: str | None,
    client_id: uuid.UUID | None,
    overdue: bool,
    limit: int,
    offset: int,
) -> tuple[list[Invoice], int]:
    from sqlalchemy import func

    set_org_context(db, org_id)
    conds: list[Any] = [Invoice.org_id == org_id]
    if status:
        conds.append(Invoice.status == status)
    if client_id:
        conds.append(Invoice.client_id == client_id)
    if overdue:
        conds += [Invoice.status.in_(PAYABLE), Invoice.due_date < utcnow().date()]
    items = list(
        db.scalars(
            select(Invoice)
            .where(*conds)
            .order_by(Invoice.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    total = db.scalar(select(func.count()).select_from(Invoice).where(*conds)) or 0
    return items, total
