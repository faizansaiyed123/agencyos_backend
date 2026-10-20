"""HTTP routes for the proposals module."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db, set_org_context
from app.core.errors import NotFound
from app.core.pagination import Page, PageDep
from app.core.permissions import Perm
from app.modules.identity.deps import CurrentUser, require
from app.modules.proposals import queries, service
from app.modules.proposals.schemas import (
    ProposalCreateRequest,
    ProposalItemCreateRequest,
    ProposalItemOut,
    ProposalItemUpdateRequest,
    ProposalOut,
    ProposalRejectRequest,
    ProposalWithItemsOut,
)

router = APIRouter(tags=["proposals"])


@router.post("/proposals", response_model=ProposalOut, status_code=201)
def create_proposal(
    body: ProposalCreateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ProposalOut:
    proposal = service.create_proposal(
        db, org_id=user.org_id, actor_id=user.id, client_id=body.client_id, deal_id=body.deal_id,
        title=body.title, currency=body.currency, valid_until=body.valid_until,
    )  # fmt: skip
    return ProposalOut.model_validate(proposal)


@router.get("/proposals", response_model=Page[ProposalOut])
def list_proposals(
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_READ))],
    db: Annotated[Session, Depends(get_db)],
    page: PageDep,
    deal_id: uuid.UUID | None = None,
    status: str | None = None,
) -> Page[ProposalOut]:
    set_org_context(db, user.org_id)
    items, total = queries.list_proposals(
        db, user.org_id, deal_id=deal_id, status=status, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[ProposalOut.model_validate(i) for i in items], total=total,
        limit=page.limit, offset=page.offset,
    )  # fmt: skip


@router.get("/proposals/{proposal_id}", response_model=ProposalWithItemsOut)
def get_proposal(
    proposal_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> ProposalWithItemsOut:
    set_org_context(db, user.org_id)
    proposal = queries.get_proposal(db, user.org_id, proposal_id)
    if proposal is None:
        raise NotFound("Proposal not found")
    items = queries.list_items(db, user.org_id, proposal_id)
    total = queries.compute_total(db, user.org_id, proposal_id)
    return ProposalWithItemsOut(
        proposal=ProposalOut.model_validate(proposal),
        items=[ProposalItemOut.model_validate(i) for i in items],
        total_amount=total,
    )


@router.post("/proposals/{proposal_id}/items", response_model=ProposalItemOut, status_code=201)
def add_item(
    proposal_id: uuid.UUID,
    body: ProposalItemCreateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ProposalItemOut:
    item = service.add_item(
        db, org_id=user.org_id, actor_id=user.id, proposal_id=proposal_id,
        description=body.description, quantity=body.quantity, unit_amount=body.unit_amount,
        position=body.position,
    )  # fmt: skip
    return ProposalItemOut.model_validate(item)


@router.patch("/proposal-items/{item_id}", response_model=ProposalItemOut)
def update_item(
    item_id: uuid.UUID,
    body: ProposalItemUpdateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ProposalItemOut:
    item = service.update_item(
        db, org_id=user.org_id, actor_id=user.id, item_id=item_id, description=body.description,
        quantity=body.quantity, unit_amount=body.unit_amount, position=body.position,
    )  # fmt: skip
    return ProposalItemOut.model_validate(item)


@router.delete("/proposal-items/{item_id}", status_code=204)
def remove_item(
    item_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    service.remove_item(db, org_id=user.org_id, actor_id=user.id, item_id=item_id)


@router.post("/proposals/{proposal_id}/send", response_model=ProposalOut)
def send_proposal(
    proposal_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ProposalOut:
    proposal = service.send_proposal(
        db, org_id=user.org_id, actor_id=user.id, proposal_id=proposal_id
    )
    return ProposalOut.model_validate(proposal)


@router.post("/proposals/{proposal_id}/accept", response_model=ProposalOut)
def accept_proposal(
    proposal_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ProposalOut:
    proposal = service.accept_proposal(
        db, org_id=user.org_id, actor_id=user.id, proposal_id=proposal_id
    )
    return ProposalOut.model_validate(proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(
    proposal_id: uuid.UUID,
    body: ProposalRejectRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.PROPOSAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ProposalOut:
    proposal = service.reject_proposal(
        db, org_id=user.org_id, actor_id=user.id, proposal_id=proposal_id, reason=body.reason
    )
    return ProposalOut.model_validate(proposal)
