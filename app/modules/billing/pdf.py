from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.modules.billing.invoice_states import settlement
from app.modules.billing.models import CreditNote, Invoice, InvoiceLine
from app.modules.crm.models import Client


def render_invoice_pdf(invoice: Invoice, client: Client, lines: Iterable[InvoiceLine]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=invoice.number or "AgencyOS Invoice",
        author="AgencyOS",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "AgencyTitle", parent=styles["Title"], fontSize=22, leading=26, spaceAfter=6
    )
    meta = ParagraphStyle(
        "AgencyMeta",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#667080"),
    )
    _right = ParagraphStyle(
        "AgencyRight", parent=styles["BodyText"], fontSize=10, alignment=TA_RIGHT
    )

    story: list[object] = [
        Paragraph("AgencyOS", title),
        Paragraph(invoice.number or "Draft invoice", styles["Heading2"]),
        Spacer(1, 6),
        Paragraph(f"Bill to: {escape(client.name)}", styles["BodyText"]),
    ]
    if client.website:
        story.append(Paragraph(escape(client.website), meta))
    story.append(Spacer(1, 10))

    issued = invoice.issue_date.isoformat() if isinstance(invoice.issue_date, date) else "-"
    due = invoice.due_date.isoformat() if isinstance(invoice.due_date, date) else "-"
    story.append(
        Table(
            [
                ["Issue date", issued, "Due date", due],
                ["Currency", invoice.currency, "Status", invoice.status.replace("_", " ").title()],
            ],
            colWidths=[27 * mm, 35 * mm, 27 * mm, 55 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f5f7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d3d9e0")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]),
        )
    )
    story.append(Spacer(1, 14))

    rows = [["Description", "Qty", "Unit", "Amount"]]
    for line in lines:
        rows.append([
            escape(line.description),
            str(line.quantity),
            f"{line.unit_cents / 100:.2f} {invoice.currency}",
            f"{line.amount_cents / 100:.2f} {invoice.currency}",
        ])
    rows.extend([
        ["", "", "Subtotal", f"{invoice.subtotal_cents / 100:.2f} {invoice.currency}"],
        [
            "",
            "",
            f"Tax ({invoice.tax_rate_bps / 100:.2f}%)",
            f"{invoice.tax_cents / 100:.2f} {invoice.currency}",
        ],
        ["", "", "Total", f"{invoice.total_cents / 100:.2f} {invoice.currency}"],
        ["", "", "Paid", f"{invoice.amount_paid_cents / 100:.2f} {invoice.currency}"],
        [
            "",
            "",
            "Refunded",
            f"{invoice.amount_refunded_cents / 100:.2f} {invoice.currency}",
        ],
        [
            "",
            "",
            "Credit notes",
            f"{invoice.credit_note_cents / 100:.2f} {invoice.currency}",
        ],
        [
            "",
            "",
            "Balance",
            f"{settlement(total_cents=invoice.total_cents, amount_paid_cents=invoice.amount_paid_cents, amount_refunded_cents=invoice.amount_refunded_cents, credit_note_cents=invoice.credit_note_cents)[1] / 100:.2f} {invoice.currency}",
        ],
        [
            "",
            "",
            "Client credit",
            f"{settlement(total_cents=invoice.total_cents, amount_paid_cents=invoice.amount_paid_cents, amount_refunded_cents=invoice.amount_refunded_cents, credit_note_cents=invoice.credit_note_cents)[2] / 100:.2f} {invoice.currency}",
        ],
    ])

    story.append(
        Table(
            rows,
            colWidths=[86 * mm, 20 * mm, 35 * mm, 35 * mm],
            repeatRows=1,
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#151a22")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d3d9e0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("LINEABOVE", (2, -8), (-1, -1), 0.7, colors.HexColor("#151a22")),
                ("FONTNAME", (2, -6), (-1, -1), "Helvetica-Bold"),
            ]),
        )
    )

    if invoice.notes:
        story.extend([
            Spacer(1, 14),
            Paragraph("Notes", styles["Heading3"]),
            Paragraph(escape(invoice.notes), styles["BodyText"]),
        ])

    story.extend([Spacer(1, 20), Paragraph("Generated by AgencyOS", meta)])
    doc.build(story)
    return buffer.getvalue()



def render_credit_note_pdf(credit_note: CreditNote, invoice: Invoice, client: Client) -> bytes:
    """Render a formal, immutable credit-note document tied to its source invoice."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=credit_note.number,
        author="AgencyOS",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "AgencyCreditTitle", parent=styles["Title"], fontSize=22, leading=26, spaceAfter=6
    )
    meta = ParagraphStyle(
        "AgencyCreditMeta",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#667080"),
    )
    _, amount_due, client_credit = settlement(
        total_cents=invoice.total_cents,
        amount_paid_cents=invoice.amount_paid_cents,
        amount_refunded_cents=invoice.amount_refunded_cents,
        credit_note_cents=invoice.credit_note_cents,
    )
    story: list[object] = [
        Paragraph("AgencyOS", title),
        Paragraph("Credit note " + escape(credit_note.number), styles["Heading2"]),
        Spacer(1, 8),
        Paragraph("Issued to: " + escape(client.name), styles["BodyText"]),
        Paragraph("Original invoice: " + escape(invoice.number or str(invoice.id)), meta),
        Spacer(1, 10),
        Table(
            [
                ["Credit note date", credit_note.issued_on.isoformat()],
                ["Currency", invoice.currency],
            ],
            colWidths=[42 * mm, 95 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f5f7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d3d9e0")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]),
        ),
        Spacer(1, 18),
        Paragraph("Reason", styles["Heading3"]),
        Paragraph(escape(credit_note.reason), styles["BodyText"]),
        Spacer(1, 14),
        Table(
            [
                ["Credit note amount", f"{credit_note.amount_cents / 100:.2f} {invoice.currency}"],
                ["Original invoice total", f"{invoice.total_cents / 100:.2f} {invoice.currency}"],
                ["Total credits issued", f"{invoice.credit_note_cents / 100:.2f} {invoice.currency}"],
                ["Outstanding balance", f"{amount_due / 100:.2f} {invoice.currency}"],
                ["Client credit balance", f"{client_credit / 100:.2f} {invoice.currency}"],
            ],
            colWidths=[90 * mm, 47 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f5f7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d3d9e0")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 7),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]),
        ),
        Spacer(1, 20),
        Paragraph(
            "This document records a reduction to the original invoice. "
            "Any cash refund is recorded separately against the original payment.",
            meta,
        ),
        Spacer(1, 20),
        Paragraph("Generated by AgencyOS", meta),
    ]
    doc.build(story)
    return buffer.getvalue()
