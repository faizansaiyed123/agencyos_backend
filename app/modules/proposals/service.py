"""Proposals business logic: draft/edit -> send -> accept/reject/expire, and
the brief's central workflow — accepting a proposal moves its deal to 'won'.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import set_org_context
from app.core.errors import BusinessRuleViolation, Conflict, NotFound
from app.modules.crm import queries as crm_queries
from app.modules.crm import service as crm_service
from app.modules.crm.deal_states import HAPPY_PATH_ORDER
from app.modules.projects import service as projects_service
from app.modules.proposals import queries
from app.modules.proposals.models import Proposal, ProposalItem
from app.modules.proposals.proposal_states import can_transition, is_editable
from app.platform import jobs
from app.platform.audit import record_audit


def create_proposal(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    client_id: uuid.UUID,
    deal_id: uuid.UUID,
    title: str,
    currency: str,
    valid_until: date | None,
) -> Proposal:
    set_org_context(db, org_id)
    deal = crm_queries.get_deal(db, org_id, deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    if deal.client_id != client_id:
        raise BusinessRuleViolation(
            "client_id does not match the deal's client", code="client_deal_mismatch"
        )
    if deal.stage == "lost":
        raise Conflict("Cannot create a proposal for a deal marked lost", code="deal_closed")

    proposal = Proposal(
        org_id=org_id, client_id=client_id, deal_id=deal_id, title=title, status="draft",
        currency=currency, valid_until=valid_until, created_by=actor_id,
    )  # fmt: skip
    db.add(proposal)
    db.flush()
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="proposal.created",
        entity_type="proposal", entity_id=proposal.id, data={"deal_id": str(deal_id)},
    )  # fmt: skip
    db.commit()
    return proposal


def _get_editable_proposal(db: Session, org_id: uuid.UUID, proposal_id: uuid.UUID) -> Proposal:
    proposal = queries.get_proposal(db, org_id, proposal_id)
    if proposal is None:
        raise NotFound("Proposal not found")
    if not is_editable(proposal.status):
        raise Conflict(
            f"Cannot modify a proposal that is '{proposal.status}' — only drafts are editable",
            code="proposal_not_editable",
        )
    return proposal


def add_item(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    proposal_id: uuid.UUID,
    description: str,
    quantity: Decimal,
    unit_amount: int,
    position: int,
) -> ProposalItem:
    set_org_context(db, org_id)
    _get_editable_proposal(db, org_id, proposal_id)

    item = ProposalItem(
        org_id=org_id, proposal_id=proposal_id, description=description,
        quantity=quantity, unit_amount=unit_amount, position=position,
    )  # fmt: skip
    db.add(item)
    db.flush()
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="proposal_item.added",
        entity_type="proposal_item", entity_id=item.id, data={"proposal_id": str(proposal_id)},
    )  # fmt: skip
    db.commit()
    return item


def update_item(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    item_id: uuid.UUID,
    description: str | None,
    quantity: Decimal | None,
    unit_amount: int | None,
    position: int | None,
) -> ProposalItem:
    set_org_context(db, org_id)
    item = queries.get_item(db, org_id, item_id)
    if item is None:
        raise NotFound("Proposal item not found")
    _get_editable_proposal(db, org_id, item.proposal_id)

    if description is not None:
        item.description = description
    if quantity is not None:
        item.quantity = quantity
    if unit_amount is not None:
        item.unit_amount = unit_amount
    if position is not None:
        item.position = position

    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="proposal_item.updated",
        entity_type="proposal_item", entity_id=item.id,
    )  # fmt: skip
    db.commit()
    return item


def remove_item(db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, item_id: uuid.UUID) -> None:
    set_org_context(db, org_id)
    item = queries.get_item(db, org_id, item_id)
    if item is None:
        raise NotFound("Proposal item not found")
    _get_editable_proposal(db, org_id, item.proposal_id)

    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="proposal_item.removed",
        entity_type="proposal_item", entity_id=item.id,
    )  # fmt: skip
    db.delete(item)
    db.commit()


def send_proposal(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, proposal_id: uuid.UUID
) -> Proposal:
    set_org_context(db, org_id)
    proposal = queries.get_proposal(db, org_id, proposal_id)
    if proposal is None:
        raise NotFound("Proposal not found")
    if not can_transition(proposal.status, "sent"):
        raise Conflict(
            f"Cannot send a proposal that is '{proposal.status}'", code="invalid_status_transition"
        )

    items = queries.list_items(db, org_id, proposal_id)
    if not items:
        raise BusinessRuleViolation(
            "Cannot send a proposal with no line items", code="proposal_has_no_items"
        )

    proposal.status = "sent"
    proposal.sent_at = utcnow()

    if proposal.valid_until is not None:
        # Expire the day after valid_until, at midnight UTC — its own delayed
        # job, scoped to this org, no cross-tenant sweep needed (see jobs.py).
        run_after = datetime.combine(proposal.valid_until, datetime.min.time()) + timedelta(days=1)
        jobs.enqueue(
            db, job_type="expire_proposal_if_overdue", org_id=org_id,
            payload={"org_id": str(org_id), "proposal_id": str(proposal.id)}, run_after=run_after,
        )  # fmt: skip

    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="proposal.sent",
        entity_type="proposal", entity_id=proposal.id,
    )  # fmt: skip
    db.commit()
    return proposal


def accept_proposal(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, proposal_id: uuid.UUID
) -> Proposal:
    """The brief's central workflow: accepting a proposal moves its deal to
    'won' in the same transaction. The deal's value is synced from the
    proposal's line-item total first, since 'won' requires a positive value
    (see crm.service.change_deal_stage) and the two are meant to agree.

    An accepted proposal is authoritative evidence the deal is won regardless
    of which intermediate stage (lead/qualified/proposal_sent/negotiation) it
    was still sitting at — the client signed, so the remaining pipeline
    formalities are moot. Rather than attempting a single jump the state
    machine correctly forbids (no skipping stages), this walks the deal
    forward one stage at a time along deal_states.HAPPY_PATH_ORDER, so every
    individual transition is still validated and recorded in
    DealStageHistory, just all at once.
    """
    set_org_context(db, org_id)
    proposal = queries.get_proposal(db, org_id, proposal_id)
    if proposal is None:
        raise NotFound("Proposal not found")
    if not can_transition(proposal.status, "accepted"):
        raise Conflict(
            f"Cannot accept a proposal that is '{proposal.status}'",
            code="invalid_status_transition",
        )

    total = queries.compute_total(db, org_id, proposal_id)
    if total <= 0:
        raise BusinessRuleViolation(
            "Cannot accept a proposal with a zero total", code="proposal_has_no_value"
        )

    deal = crm_queries.get_deal(db, org_id, proposal.deal_id)
    if deal is None:
        raise NotFound("The deal linked to this proposal no longer exists")
    if deal.stage == "lost":
        raise Conflict(
            "The linked deal was already marked lost", code="deal_stage_blocks_acceptance"
        )

    proposal.status = "accepted"
    proposal.accepted_at = utcnow()
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="proposal.accepted",
        entity_type="proposal", entity_id=proposal.id, data={"total": total},
    )  # fmt: skip
    # Acceptance converts into a project (budget + one milestone per line item) in the
    # SAME transaction, idempotently per deal: the client signed, so delivery begins.
    projects_service.create_project_from_deal(
        db,
        org_id=org_id,
        actor_id=actor_id,
        deal_id=deal.id,
        client_id=proposal.client_id,
        proposal_id=proposal.id,
        name=deal.title,
        budget_amount=total,
        currency=proposal.currency,
        milestones=[
            (item.description[:200], int(item.quantity * item.unit_amount))
            for item in queries.list_items(db, org_id, proposal_id)
        ],
        manager_user_id=deal.owner_user_id,
    )

    if deal.stage != "won":
        crm_service.set_deal_value(
            db, org_id=org_id, actor_id=actor_id, deal_id=deal.id,
            value_amount=total, commit=False,
        )
        current_index = HAPPY_PATH_ORDER.index(deal.stage)
        for next_stage in HAPPY_PATH_ORDER[current_index + 1 :]:
            note = (
                f"Won via accepted proposal: {proposal.title}"
                if next_stage == "won"
                else f"Auto-advanced on proposal acceptance: {proposal.title}"
            )
            crm_service.change_deal_stage(
                db, org_id=org_id, actor_id=actor_id, deal_id=deal.id, to_stage=next_stage,
                lost_reason=None, note=note, commit=False,
            )  # fmt: skip

    return proposal


def reject_proposal(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, proposal_id: uuid.UUID, reason: str
) -> Proposal:
    set_org_context(db, org_id)
    proposal = queries.get_proposal(db, org_id, proposal_id)
    if proposal is None:
        raise NotFound("Proposal not found")
    if not can_transition(proposal.status, "rejected"):
        raise Conflict(
            f"Cannot reject a proposal that is '{proposal.status}'",
            code="invalid_status_transition",
        )

    proposal.status = "rejected"
    proposal.rejected_at = utcnow()
    proposal.rejection_reason = reason
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="proposal.rejected",
        entity_type="proposal", entity_id=proposal.id, data={"reason": reason},
    )  # fmt: skip
    db.commit()
    return proposal
