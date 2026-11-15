import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.billing.pdf import render_credit_note_pdf, render_invoice_pdf
from app.modules.identity.deps import CurrentUser
from app.modules.portal import service
from app.modules.portal.schemas import (
    PortalCreditNoteOut,
    PortalInvoiceOut,
    PortalOverviewOut,
    PortalProjectOut,
    PortalProposalDetailOut,
    PortalProposalOut,
    PortalRejectRequest,
)

router = APIRouter(prefix="/portal", tags=["client portal"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/overview", response_model=PortalOverviewOut)
def overview(user: CurrentUser, db: Db) -> PortalOverviewOut:
    return service.overview(db, user)


@router.get("/projects", response_model=list[PortalProjectOut])
def projects(user: CurrentUser, db: Db) -> list[PortalProjectOut]:
    return service.projects(db, user)


@router.get("/proposals", response_model=list[PortalProposalOut])
def proposals(user: CurrentUser, db: Db) -> list[PortalProposalOut]:
    return service.proposals(db, user)


@router.get("/proposals/{proposal_id}", response_model=PortalProposalDetailOut)
def proposal(proposal_id: uuid.UUID, user: CurrentUser, db: Db) -> PortalProposalDetailOut:
    return service.proposal(db, user, proposal_id)


@router.post("/proposals/{proposal_id}/accept", response_model=PortalProposalDetailOut)
def accept_proposal(
    proposal_id: uuid.UUID, user: CurrentUser, db: Db
) -> PortalProposalDetailOut:
    return service.accept_proposal(db, user, proposal_id)


@router.post("/proposals/{proposal_id}/reject", response_model=PortalProposalDetailOut)
def reject_proposal(
    proposal_id: uuid.UUID,
    body: PortalRejectRequest,
    user: CurrentUser,
    db: Db,
) -> PortalProposalDetailOut:
    return service.reject_proposal(db, user, proposal_id, body.reason)


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: uuid.UUID, user: CurrentUser, db: Db) -> Response:
    invoice, client, lines = service.invoice_pdf_data(db, user, invoice_id)
    return Response(
        content=render_invoice_pdf(invoice, client, lines),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{invoice.number or "invoice"}.pdf"',
        },
    )


@router.get("/invoices", response_model=list[PortalInvoiceOut])
def invoices(user: CurrentUser, db: Db) -> list[PortalInvoiceOut]:
    return service.invoices(db, user)



@router.get("/credit-notes", response_model=list[PortalCreditNoteOut])
def credit_notes(user: CurrentUser, db: Db) -> list[PortalCreditNoteOut]:
    return service.credit_notes(db, user)


@router.get("/credit-notes/{credit_note_id}/pdf")
def credit_note_pdf(credit_note_id: uuid.UUID, user: CurrentUser, db: Db) -> Response:
    note, invoice, client = service.credit_note_pdf_data(db, user, credit_note_id)
    return Response(
        content=render_credit_note_pdf(note, invoice, client),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{note.number}.pdf"',
        },
    )
