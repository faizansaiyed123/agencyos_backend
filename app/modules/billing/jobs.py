from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.billing.models import Invoice, InvoiceLine
from app.modules.billing.pdf import render_invoice_pdf
from app.modules.crm.models import Client, Contact
from app.platform import jobs
from app.platform.email import send_email


def _send_invoice_email(payload: dict[str, Any], db: Session) -> None:
    org_id = payload["org_id"]
    invoice_id = payload["invoice_id"]
    invoice = db.scalar(
        select(Invoice).where(Invoice.org_id == org_id, Invoice.id == invoice_id)
    )
    if invoice is None:
        raise RuntimeError("Invoice not found")

    client = db.scalar(
        select(Client).where(Client.org_id == org_id, Client.id == invoice.client_id)
    )
    contact = db.scalar(
        select(Contact)
        .where(
            Contact.org_id == org_id,
            Contact.client_id == invoice.client_id,
            Contact.email.is_not(None),
        )
        .order_by(Contact.is_primary.desc(), Contact.created_at)
    )
    if client is None or contact is None or not contact.email:
        raise RuntimeError("Invoice email requires a client contact with an email address")

    lines = list(
        db.scalars(
            select(InvoiceLine)
            .where(
                InvoiceLine.org_id == org_id,
                InvoiceLine.invoice_id == invoice.id,
            )
            .order_by(InvoiceLine.position, InvoiceLine.created_at)
        )
    )
    pdf = render_invoice_pdf(invoice, client, lines)
    number = invoice.number or "invoice"
    balance = invoice.total_cents - invoice.amount_paid_cents
    send_email(
        to=contact.email,
        subject=f"Invoice {number} from {client.name}",
        body=(
            f"Hello,\n\nPlease find invoice {number} attached. "
            f"Outstanding balance: {balance / 100:.2f} {invoice.currency}.\n\n"
            "Thank you."
        ),
        attachments=[{
            "filename": f"{number}.pdf",
            "data": pdf,
            "maintype": "application",
            "subtype": "pdf",
        }],
    )


def register() -> None:
    jobs.register_handler("send_invoice_email", _send_invoice_email)
