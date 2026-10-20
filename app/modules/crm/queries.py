"""Plain data-access functions for the CRM module."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.crm.models import Client, Contact, Deal, DealStageHistory


def get_client(db: Session, org_id: uuid.UUID, client_id: uuid.UUID) -> Client | None:
    return db.scalar(select(Client).where(Client.org_id == org_id, Client.id == client_id))


def list_clients(
    db: Session, org_id: uuid.UUID, *, include_archived: bool, limit: int, offset: int
) -> tuple[list[Client], int]:
    conditions = [Client.org_id == org_id]
    if not include_archived:
        conditions.append(Client.archived_at.is_(None))
    items = list(
        db.scalars(
            select(Client).where(*conditions).order_by(Client.name).limit(limit).offset(offset)
        )
    )
    total = db.scalar(select(func.count()).select_from(Client).where(*conditions)) or 0
    return items, total


def get_contact(db: Session, org_id: uuid.UUID, contact_id: uuid.UUID) -> Contact | None:
    return db.scalar(select(Contact).where(Contact.org_id == org_id, Contact.id == contact_id))


def list_contacts_for_client(db: Session, org_id: uuid.UUID, client_id: uuid.UUID) -> list[Contact]:
    return list(
        db.scalars(
            select(Contact)
            .where(Contact.org_id == org_id, Contact.client_id == client_id)
            .order_by(Contact.is_primary.desc(), Contact.full_name)
        )
    )


def get_deal(db: Session, org_id: uuid.UUID, deal_id: uuid.UUID) -> Deal | None:
    return db.scalar(select(Deal).where(Deal.org_id == org_id, Deal.id == deal_id))


def list_deals(
    db: Session,
    org_id: uuid.UUID,
    *,
    stage: str | None,
    client_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[Deal], int]:
    conditions = [Deal.org_id == org_id]
    if stage is not None:
        conditions.append(Deal.stage == stage)
    if client_id is not None:
        conditions.append(Deal.client_id == client_id)
    items = list(
        db.scalars(
            select(Deal)
            .where(*conditions)
            .order_by(Deal.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    total = db.scalar(select(func.count()).select_from(Deal).where(*conditions)) or 0
    return items, total


def list_deal_stage_history(
    db: Session, org_id: uuid.UUID, deal_id: uuid.UUID
) -> list[DealStageHistory]:
    return list(
        db.scalars(
            select(DealStageHistory)
            .where(DealStageHistory.org_id == org_id, DealStageHistory.deal_id == deal_id)
            .order_by(DealStageHistory.created_at)
        )
    )
