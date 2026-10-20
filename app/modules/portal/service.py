import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import set_org_context
from app.core.errors import Forbidden, NotFound
from app.core.permissions import Role
from app.modules.billing.models import Invoice
from app.modules.crm.models import Client
from app.modules.identity.models import User
from app.modules.projects.models import Project
from app.modules.proposals import service as proposal_service
from app.modules.proposals.models import Proposal, ProposalItem
from app.modules.portal.schemas import (
    PortalClientOut,
    PortalInvoiceOut,
    PortalOverviewOut,
    PortalProjectOut,
    PortalProposalDetailOut,
    PortalProposalItemOut,
    PortalProposalOut,
)


def _client_id(user: User) -> uuid.UUID:
    if Role(user.role) != Role.CLIENT or user.client_id is None:
        raise Forbidden("Client portal access is only available to client accounts")
    return user.client_id


def _context(db: Session, user: User) -> tuple[uuid.UUID, Client]:
    cid = _client_id(user)
    set_org_context(db, user.org_id)
    client = db.scalar(
        select(Client).where(
            Client.org_id == user.org_id,
            Client.id == cid,
            Client.archived_at.is_(None),
        )
    )
    if client is None:
        raise NotFound("Client relationship not found")
    return cid, client


def _proposal_out(db: Session, org_id: uuid.UUID, proposal: Proposal) -> PortalProposalOut:
    total = db.scalar(
        select(func.coalesce(func.sum(ProposalItem.quantity * ProposalItem.unit_amount), 0)).where(
            ProposalItem.org_id == org_id,
            ProposalItem.proposal_id == proposal.id,
        )
    )
    return PortalProposalOut(
        id=proposal.id,
        title=proposal.title,
        status=proposal.status,
        currency=proposal.currency,
        valid_until=proposal.valid_until,
        sent_at=proposal.sent_at,
        accepted_at=proposal.accepted_at,
        rejected_at=proposal.rejected_at,
        rejection_reason=proposal.rejection_reason,
        total_amount=int(total or 0),
    )


def _invoice_out(invoice: Invoice) -> PortalInvoiceOut:
    return PortalInvoiceOut(
        id=invoice.id,
        number=invoice.number,
        status=invoice.status,
        currency=invoice.currency,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        total_cents=invoice.total_cents,
        amount_paid_cents=invoice.amount_paid_cents,
        balance_cents=invoice.total_cents - invoice.amount_paid_cents,
        notes=invoice.notes,
    )


def overview(db: Session, user: User) -> PortalOverviewOut:
    cid, client = _context(db, user)
    projects = list(
        db.scalars(
            select(Project)
            .where(Project.org_id == user.org_id, Project.client_id == cid)
            .order_by(Project.updated_at.desc())
            .limit(20)
        )
    )
    proposals = list(
        db.scalars(
            select(Proposal)
            .where(
                Proposal.org_id == user.org_id,
                Proposal.client_id == cid,
                Proposal.status.in_(("sent", "accepted", "rejected", "expired")),
            )
            .order_by(Proposal.created_at.desc())
            .limit(20)
        )
    )
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.org_id == user.org_id,
                Invoice.client_id == cid,
                Invoice.status != "draft",
            )
            .order_by(Invoice.created_at.desc())
            .limit(20)
        )
    )
    return PortalOverviewOut(
        client=PortalClientOut(
            id=client.id,
            name=client.name,
            industry=client.industry,
            website=client.website,
        ),
        projects=[PortalProjectOut.model_validate(p) for p in projects],
        proposals=[_proposal_out(db, user.org_id, p) for p in proposals],
        invoices=[_invoice_out(i) for i in invoices],
    )


def projects(db: Session, user: User) -> list[PortalProjectOut]:
    cid, _ = _context(db, user)
    rows = db.scalars(
        select(Project)
        .where(Project.org_id == user.org_id, Project.client_id == cid)
        .order_by(Project.updated_at.desc())
    )
    return [PortalProjectOut.model_validate(p) for p in rows]


def proposals(db: Session, user: User) -> list[PortalProposalOut]:
    cid, _ = _context(db, user)
    rows = db.scalars(
        select(Proposal)
        .where(
            Proposal.org_id == user.org_id,
            Proposal.client_id == cid,
            Proposal.status.in_(("sent", "accepted", "rejected", "expired")),
        )
        .order_by(Proposal.created_at.desc())
    )
    return [_proposal_out(db, user.org_id, p) for p in rows]


def proposal(db: Session, user: User, proposal_id: uuid.UUID) -> PortalProposalDetailOut:
    cid, _ = _context(db, user)
    item = db.scalar(
        select(Proposal).where(
            Proposal.org_id == user.org_id,
            Proposal.id == proposal_id,
            Proposal.client_id == cid,
            Proposal.status != "draft",
        )
    )
    if item is None:
        raise NotFound("Proposal not found")
    items = db.scalars(
        select(ProposalItem)
        .where(
            ProposalItem.org_id == user.org_id,
            ProposalItem.proposal_id == item.id,
        )
        .order_by(ProposalItem.position, ProposalItem.created_at)
    )
    return PortalProposalDetailOut(
        proposal=_proposal_out(db, user.org_id, item),
        items=[
            PortalProposalItemOut(
                id=line.id,
                description=line.description,
                quantity=str(line.quantity),
                unit_amount=line.unit_amount,
                amount=int(Decimal(line.quantity) * line.unit_amount),
                position=line.position,
            )
            for line in items
        ],
    )


def accept_proposal(db: Session, user: User, proposal_id: uuid.UUID) -> PortalProposalDetailOut:
    cid, _ = _context(db, user)
    item = db.scalar(
        select(Proposal).where(
            Proposal.org_id == user.org_id,
            Proposal.id == proposal_id,
            Proposal.client_id == cid,
        )
    )
    if item is None:
        raise NotFound("Proposal not found")
    proposal_service.accept_proposal(
        db,
        org_id=user.org_id,
        actor_id=user.id,
        proposal_id=proposal_id,
    )
    return proposal(db, user, proposal_id)


def reject_proposal(
    db: Session, user: User, proposal_id: uuid.UUID, reason: str
) -> PortalProposalDetailOut:
    cid, _ = _context(db, user)
    item = db.scalar(
        select(Proposal).where(
            Proposal.org_id == user.org_id,
            Proposal.id == proposal_id,
            Proposal.client_id == cid,
        )
    )
    if item is None:
        raise NotFound("Proposal not found")
    proposal_service.reject_proposal(
        db,
        org_id=user.org_id,
        actor_id=user.id,
        proposal_id=proposal_id,
        reason=reason,
    )
    return proposal(db, user, proposal_id)


def invoices(db: Session, user: User) -> list[PortalInvoiceOut]:
    cid, _ = _context(db, user)
    rows = db.scalars(
        select(Invoice)
        .where(
            Invoice.org_id == user.org_id,
            Invoice.client_id == cid,
            Invoice.status != "draft",
        )
        .order_by(Invoice.created_at.desc())
    )
    return [_invoice_out(i) for i in rows]
