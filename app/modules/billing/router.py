import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import BusinessRuleViolation, Conflict, NotFound
from app.core.pagination import Page, PageDep
from app.core.permissions import Perm
from app.modules.billing import service
from app.modules.billing.models import Invoice
from app.modules.billing.pdf import render_invoice_pdf
from app.modules.billing.schemas import (
    InvoiceCreateRequest,
    InvoiceDetailOut,
    InvoiceOut,
    InvoiceUpdateRequest,
    LineCreateRequest,
    LineOut,
    MilestoneLineRequest,
    PaymentOut,
    PaymentRequest,
    TimeLinesRequest,
    UnbilledRow,
    VoidRequest,
)
from app.modules.crm.models import Contact
from app.modules.identity.deps import require
from app.modules.identity.models import User
from app.modules.time.models import amount_cents
from app.platform import idempotency

router = APIRouter(tags=["billing"])
Db = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(require(Perm.INVOICE_READ))]
Manager = Annotated[User, Depends(require(Perm.INVOICE_MANAGE))]


def _out(inv: Invoice) -> InvoiceOut:
    o = InvoiceOut.model_validate(inv)
    o.balance_cents = service.balance(inv)
    o.is_overdue = service.is_overdue(inv)
    return o


def _detail(db: Session, inv: Invoice) -> InvoiceDetailOut:
    return InvoiceDetailOut(
        invoice=_out(inv),
        lines=[LineOut.model_validate(x) for x in service.lines_of(db, inv.org_id, inv.id)],
        payments=[
            PaymentOut.model_validate(x) for x in service.payments_of(db, inv.org_id, inv.id)
        ],
    )


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create(body: InvoiceCreateRequest, user: Manager, db: Db) -> InvoiceOut:
    return _out(
        service.create_invoice(db, org_id=user.org_id, actor_id=user.id, **body.model_dump())
    )


@router.get("/invoices", response_model=Page[InvoiceOut])
def list_(
    user: Reader,
    db: Db,
    page: PageDep,
    status: str | None = None,
    client_id: uuid.UUID | None = None,
    overdue: bool = False,
) -> Page[InvoiceOut]:
    items, total = service.list_invoices(
        db,
        org_id=user.org_id,
        status=status,
        client_id=client_id,
        overdue=overdue,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(items=[_out(i) for i in items], total=total, limit=page.limit, offset=page.offset)


@router.get("/invoices/unbilled-time", response_model=list[UnbilledRow])
def unbilled(project_id: uuid.UUID, user: Reader, db: Db) -> list[UnbilledRow]:
    return [
        UnbilledRow(
            entry_id=e.id,
            user_id=e.user_id,
            entry_date=e.entry_date,
            minutes=e.minutes,
            rate_cents=e.rate_cents,
            amount_cents=amount_cents(e.minutes, e.rate_cents),
        )
        for e in service.unbilled_entries(db, user.org_id, project_id)
    ]


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
def get(invoice_id: uuid.UUID, user: Reader, db: Db) -> InvoiceDetailOut:
    return _detail(db, service.get_invoice(db, user.org_id, invoice_id))


@router.patch("/invoices/{invoice_id}", response_model=InvoiceOut)
def update(invoice_id: uuid.UUID, body: InvoiceUpdateRequest, user: Manager, db: Db) -> InvoiceOut:
    return _out(
        service.update_invoice(
            db, org_id=user.org_id, actor_id=user.id, invoice_id=invoice_id, **body.model_dump()
        )
    )


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete(invoice_id: uuid.UUID, user: Manager, db: Db) -> None:
    service.delete_draft(db, org_id=user.org_id, actor_id=user.id, invoice_id=invoice_id)


@router.post("/invoices/{invoice_id}/lines", response_model=InvoiceDetailOut, status_code=201)
def add_line(
    invoice_id: uuid.UUID, body: LineCreateRequest, user: Manager, db: Db
) -> InvoiceDetailOut:
    service.add_line(
        db, org_id=user.org_id, actor_id=user.id, invoice_id=invoice_id, **body.model_dump()
    )
    return _detail(db, service.get_invoice(db, user.org_id, invoice_id))


@router.post(
    "/invoices/{invoice_id}/lines/milestone", response_model=InvoiceDetailOut, status_code=201
)
def add_milestone(
    invoice_id: uuid.UUID, body: MilestoneLineRequest, user: Manager, db: Db
) -> InvoiceDetailOut:
    service.add_milestone_line(
        db,
        org_id=user.org_id,
        actor_id=user.id,
        invoice_id=invoice_id,
        milestone_id=body.milestone_id,
    )
    return _detail(db, service.get_invoice(db, user.org_id, invoice_id))


@router.post("/invoices/{invoice_id}/lines/time", response_model=InvoiceDetailOut, status_code=201)
def add_time(
    invoice_id: uuid.UUID, body: TimeLinesRequest, user: Manager, db: Db
) -> InvoiceDetailOut:
    service.add_time_lines(
        db, org_id=user.org_id, actor_id=user.id, invoice_id=invoice_id, entry_ids=body.entry_ids
    )
    return _detail(db, service.get_invoice(db, user.org_id, invoice_id))


@router.delete("/invoices/{invoice_id}/lines/{line_id}", response_model=InvoiceDetailOut)
def remove_line(
    invoice_id: uuid.UUID, line_id: uuid.UUID, user: Manager, db: Db
) -> InvoiceDetailOut:
    service.remove_line(
        db, org_id=user.org_id, actor_id=user.id, invoice_id=invoice_id, line_id=line_id
    )
    return _detail(db, service.get_invoice(db, user.org_id, invoice_id))


@router.get("/invoices/{invoice_id}/pdf")
def pdf(invoice_id: uuid.UUID, user: Reader, db: Db) -> Response:
    inv = service.get_invoice(db, user.org_id, invoice_id)
    if inv.status == "draft":
        raise BusinessRuleViolation(
            "Draft invoices cannot be downloaded as final PDFs",
            code="invoice_not_issued",
        )
    client = service.crm_queries.get_client(db, user.org_id, inv.client_id)
    if client is None:
        raise NotFound("Client not found")
    lines = service.lines_of(db, user.org_id, inv.id)
    content = render_invoice_pdf(inv, client, lines)
    filename = f"{inv.number or 'invoice'}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/invoices/{invoice_id}/send", status_code=202, response_model=None)
def send_invoice(
    invoice_id: uuid.UUID,
    user: Manager,
    db: Db,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, str] | JSONResponse:
    fp = None
    if idempotency_key:
        fp = idempotency.fingerprint("POST", f"/invoices/{invoice_id}/send", b"")
        try:
            idempotency.check_idempotency_key(
                db, org_id=user.org_id, key=idempotency_key, request_fp=fp
            )
        except idempotency.IdempotencyReplay as replay:
            return JSONResponse(status_code=replay.status, content=replay.body)

    inv = service.get_invoice(db, user.org_id, invoice_id)
    if inv.status not in {"sent", "partially_paid", "paid"}:
        raise Conflict("Only issued invoices can be emailed", code="invoice_not_issued")
    recipient = db.scalar(
        select(Contact)
        .where(
            Contact.org_id == user.org_id,
            Contact.client_id == inv.client_id,
            Contact.email.is_not(None),
        )
        .order_by(Contact.is_primary.desc(), Contact.created_at)
    )
    if recipient is None or not recipient.email:
        raise BusinessRuleViolation(
            "Add a client contact email before sending an invoice",
            code="client_email_missing",
        )

    from app.platform import jobs
    jobs.enqueue(
        db,
        job_type="send_invoice_email",
        org_id=user.org_id,
        payload={"org_id": str(user.org_id), "invoice_id": str(invoice_id)},
    )
    body = {"message": "Invoice email queued."}
    if idempotency_key and fp:
        idempotency.store_idempotency_result(
            db,
            org_id=user.org_id,
            user_id=user.id,
            key=idempotency_key,
            request_fp=fp,
            status=202,
            body=body,
        )
    db.commit()
    return body


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceOut)
def issue(invoice_id: uuid.UUID, user: Manager, db: Db) -> InvoiceOut:
    return _out(
        service.issue_invoice(db, org_id=user.org_id, actor_id=user.id, invoice_id=invoice_id)
    )


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
def void(invoice_id: uuid.UUID, body: VoidRequest, user: Manager, db: Db) -> InvoiceOut:
    return _out(
        service.void_invoice(
            db, org_id=user.org_id, actor_id=user.id, invoice_id=invoice_id, reason=body.reason
        )
    )


@router.post("/invoices/{invoice_id}/payments", response_model=PaymentOut, status_code=201)
def pay(
    invoice_id: uuid.UUID,
    body: PaymentRequest,
    user: Manager,
    db: Db,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PaymentOut | JSONResponse:
    """Money endpoint: send an Idempotency-Key so a retried request cannot record twice."""
    fp = None
    if idempotency_key:
        fp = idempotency.fingerprint(
            "POST", f"/invoices/{invoice_id}/payments", body.model_dump_json().encode()
        )
        try:
            idempotency.check_idempotency_key(
                db, org_id=user.org_id, key=idempotency_key, request_fp=fp
            )
        except idempotency.IdempotencyReplay as replay:
            return JSONResponse(status_code=replay.status, content=replay.body)
    _inv, payment = service.record_payment(
        db,
        org_id=user.org_id,
        actor_id=user.id,
        invoice_id=invoice_id,
        amount_cents_=body.amount_cents,
        paid_on=body.paid_on,
        method=body.method,
        reference=body.reference,
        commit=not bool(idempotency_key),
    )
    out = PaymentOut.model_validate(payment)
    if idempotency_key and fp:
        idempotency.store_idempotency_result(
            db,
            org_id=user.org_id,
            user_id=user.id,
            key=idempotency_key,
            request_fp=fp,
            status=201,
            body=out.model_dump(mode="json"),
        )
        db.commit()
    return out


__all__ = ["Decimal", "router"]
