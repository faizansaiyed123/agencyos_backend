"""HTTP routes for the CRM module: clients, contacts, and the deal pipeline."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db, set_org_context
from app.core.errors import NotFound
from app.core.pagination import Page, PageDep
from app.core.permissions import Perm
from app.modules.crm import queries, service
from app.modules.crm.schemas import (
    ClientCreateRequest,
    ClientOut,
    ClientUpdateRequest,
    ContactCreateRequest,
    ContactOut,
    ContactUpdateRequest,
    DealCreateRequest,
    DealOut,
    DealStageChangeRequest,
    DealStageHistoryOut,
    DealUpdateRequest,
)
from app.modules.identity.deps import CurrentUser, require

router = APIRouter(tags=["crm"])


@router.post("/clients", response_model=ClientOut, status_code=201)
def create_client(
    body: ClientCreateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ClientOut:
    client = service.create_client(
        db, org_id=user.org_id, actor_id=user.id, name=body.name,
        industry=body.industry, website=body.website, notes=body.notes,
    )  # fmt: skip
    return ClientOut.model_validate(client)


@router.get("/clients", response_model=Page[ClientOut])
def list_clients(
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_READ))],
    db: Annotated[Session, Depends(get_db)],
    page: PageDep,
    include_archived: Annotated[bool, Query()] = False,
) -> Page[ClientOut]:
    items, total = queries.list_clients(
        db, user.org_id, include_archived=include_archived, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[ClientOut.model_validate(i) for i in items], total=total,
        limit=page.limit, offset=page.offset,
    )  # fmt: skip


@router.get("/clients/{client_id}", response_model=ClientOut)
def get_client(
    client_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> ClientOut:
    set_org_context(db, user.org_id)
    client = queries.get_client(db, user.org_id, client_id)
    if client is None:
        raise NotFound("Client not found")
    return ClientOut.model_validate(client)


@router.patch("/clients/{client_id}", response_model=ClientOut)
def update_client(
    client_id: uuid.UUID,
    body: ClientUpdateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ClientOut:
    client = service.update_client(
        db, org_id=user.org_id, actor_id=user.id, client_id=client_id, name=body.name,
        industry=body.industry, website=body.website, notes=body.notes,
    )  # fmt: skip
    return ClientOut.model_validate(client)


@router.post("/clients/{client_id}/archive", response_model=ClientOut)
def archive_client(
    client_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ClientOut:
    client = service.archive_client(db, org_id=user.org_id, actor_id=user.id, client_id=client_id)
    return ClientOut.model_validate(client)


@router.post("/clients/{client_id}/contacts", response_model=ContactOut, status_code=201)
def add_contact(
    client_id: uuid.UUID,
    body: ContactCreateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ContactOut:
    contact = service.add_contact(
        db, org_id=user.org_id, actor_id=user.id, client_id=client_id, full_name=body.full_name,
        email=body.email, phone=body.phone, title=body.title, is_primary=body.is_primary,
    )  # fmt: skip
    return ContactOut.model_validate(contact)


@router.get("/clients/{client_id}/contacts", response_model=list[ContactOut])
def list_contacts(
    client_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> list[ContactOut]:
    set_org_context(db, user.org_id)
    return [
        ContactOut.model_validate(c)
        for c in queries.list_contacts_for_client(db, user.org_id, client_id)
    ]


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: uuid.UUID,
    body: ContactUpdateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> ContactOut:
    contact = service.update_contact(
        db, org_id=user.org_id, actor_id=user.id, contact_id=contact_id, full_name=body.full_name,
        email=body.email, phone=body.phone, title=body.title, is_primary=body.is_primary,
    )  # fmt: skip
    return ContactOut.model_validate(contact)


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(
    contact_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.CLIENT_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    service.delete_contact(db, org_id=user.org_id, actor_id=user.id, contact_id=contact_id)


@router.post("/deals", response_model=DealOut, status_code=201)
def create_deal(
    body: DealCreateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.DEAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> DealOut:
    deal = service.create_deal(
        db, org_id=user.org_id, actor_id=user.id, client_id=body.client_id, title=body.title,
        description=body.description, value_amount=body.value_amount,
        value_currency=body.value_currency, owner_user_id=body.owner_user_id,
        expected_close_date=body.expected_close_date,
    )  # fmt: skip
    return DealOut.model_validate(deal)


@router.get("/deals", response_model=Page[DealOut])
def list_deals(
    user: Annotated[CurrentUser, Depends(require(Perm.DEAL_READ))],
    db: Annotated[Session, Depends(get_db)],
    page: PageDep,
    stage: Annotated[str | None, Query()] = None,
    client_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[DealOut]:
    items, total = queries.list_deals(
        db, user.org_id, stage=stage, client_id=client_id, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[DealOut.model_validate(i) for i in items], total=total,
        limit=page.limit, offset=page.offset,
    )  # fmt: skip


@router.get("/deals/{deal_id}", response_model=DealOut)
def get_deal(
    deal_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.DEAL_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> DealOut:
    set_org_context(db, user.org_id)
    deal = queries.get_deal(db, user.org_id, deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    return DealOut.model_validate(deal)


@router.patch("/deals/{deal_id}", response_model=DealOut)
def update_deal(
    deal_id: uuid.UUID,
    body: DealUpdateRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.DEAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> DealOut:
    deal = service.update_deal(
        db, org_id=user.org_id, actor_id=user.id, deal_id=deal_id, title=body.title,
        description=body.description, value_amount=body.value_amount,
        value_currency=body.value_currency, owner_user_id=body.owner_user_id,
        expected_close_date=body.expected_close_date,
    )  # fmt: skip
    return DealOut.model_validate(deal)


@router.post("/deals/{deal_id}/stage", response_model=DealOut)
def change_deal_stage(
    deal_id: uuid.UUID,
    body: DealStageChangeRequest,
    user: Annotated[CurrentUser, Depends(require(Perm.DEAL_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> DealOut:
    deal = service.change_deal_stage(
        db, org_id=user.org_id, actor_id=user.id, deal_id=deal_id, to_stage=body.to_stage,
        lost_reason=body.lost_reason, note=body.note,
    )  # fmt: skip
    return DealOut.model_validate(deal)


@router.get("/deals/{deal_id}/history", response_model=list[DealStageHistoryOut])
def deal_stage_history(
    deal_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require(Perm.DEAL_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> list[DealStageHistoryOut]:
    set_org_context(db, user.org_id)
    return [
        DealStageHistoryOut.model_validate(h)
        for h in queries.list_deal_stage_history(db, user.org_id, deal_id)
    ]
