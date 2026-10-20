"""Plain data-access functions for the proposals module."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.proposals.models import Proposal, ProposalItem


def get_proposal(db: Session, org_id: uuid.UUID, proposal_id: uuid.UUID) -> Proposal | None:
    return db.scalar(select(Proposal).where(Proposal.org_id == org_id, Proposal.id == proposal_id))


def list_proposals(
    db: Session,
    org_id: uuid.UUID,
    *,
    deal_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Proposal], int]:
    conditions = [Proposal.org_id == org_id]
    if deal_id is not None:
        conditions.append(Proposal.deal_id == deal_id)
    if status is not None:
        conditions.append(Proposal.status == status)
    items = list(
        db.scalars(
            select(Proposal)
            .where(*conditions)
            .order_by(Proposal.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    total = db.scalar(select(func.count()).select_from(Proposal).where(*conditions)) or 0
    return items, total


def get_item(db: Session, org_id: uuid.UUID, item_id: uuid.UUID) -> ProposalItem | None:
    return db.scalar(
        select(ProposalItem).where(ProposalItem.org_id == org_id, ProposalItem.id == item_id)
    )


def list_items(db: Session, org_id: uuid.UUID, proposal_id: uuid.UUID) -> list[ProposalItem]:
    return list(
        db.scalars(
            select(ProposalItem)
            .where(ProposalItem.org_id == org_id, ProposalItem.proposal_id == proposal_id)
            .order_by(ProposalItem.position, ProposalItem.created_at)
        )
    )


def compute_total(db: Session, org_id: uuid.UUID, proposal_id: uuid.UUID) -> int:
    """Computed on read (SUM over line items) rather than cached on the
    proposal row — avoids an update-anomaly where the cached total drifts
    from the items after an edit that forgot to recompute it."""
    total = db.scalar(
        select(func.coalesce(func.sum(ProposalItem.quantity * ProposalItem.unit_amount), 0)).where(
            ProposalItem.org_id == org_id, ProposalItem.proposal_id == proposal_id
        )
    )
    return int(total or 0)
