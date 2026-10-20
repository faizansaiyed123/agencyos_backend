"""CRM business logic: clients, contacts, and the deal pipeline."""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import set_org_context
from app.core.errors import BusinessRuleViolation, Conflict, NotFound
from app.modules.crm import queries
from app.modules.crm.deal_states import can_transition, is_terminal, is_valid_stage
from app.modules.crm.models import Client, Contact, Deal, DealStageHistory
from app.platform.audit import record_audit


def create_client(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    name: str,
    industry: str | None,
    website: str | None,
    notes: str | None,
) -> Client:
    set_org_context(db, org_id)
    client = Client(
        org_id=org_id, name=name, industry=industry, website=website, notes=notes,
        created_by=actor_id,
    )  # fmt: skip
    db.add(client)
    db.flush()
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="client.created",
        entity_type="client", entity_id=client.id, data={"name": name},
    )  # fmt: skip
    db.commit()
    return client


def update_client(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    client_id: uuid.UUID,
    name: str | None,
    industry: str | None,
    website: str | None,
    notes: str | None,
) -> Client:
    set_org_context(db, org_id)
    client = queries.get_client(db, org_id, client_id)
    if client is None:
        raise NotFound("Client not found")
    if client.archived_at is not None:
        raise Conflict("Cannot edit an archived client", code="client_archived")

    if name is not None:
        client.name = name
    if industry is not None:
        client.industry = industry
    if website is not None:
        client.website = website
    if notes is not None:
        client.notes = notes

    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="client.updated",
        entity_type="client", entity_id=client.id,
    )  # fmt: skip
    db.commit()
    return client


def archive_client(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, client_id: uuid.UUID
) -> Client:
    """A client with any open (non-terminal-stage) deal cannot be archived —
    resolve the pipeline first. This is an application-level rule, not a DB
    constraint, because it depends on data in a different table (deals)."""
    set_org_context(db, org_id)
    client = queries.get_client(db, org_id, client_id)
    if client is None:
        raise NotFound("Client not found")
    if client.archived_at is not None:
        raise Conflict("Client is already archived", code="client_already_archived")

    open_deal_count = db.scalar(
        select(func.count())
        .select_from(Deal)
        .where(
            Deal.org_id == org_id, Deal.client_id == client_id, Deal.stage.notin_(["won", "lost"])
        )
    )
    if open_deal_count:
        raise BusinessRuleViolation(
            f"Cannot archive a client with {open_deal_count} open deal(s); "
            "move them to won or lost first.",
            code="client_has_open_deals",
        )

    client.archived_at = utcnow()
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="client.archived",
        entity_type="client", entity_id=client.id,
    )  # fmt: skip
    db.commit()
    return client


def add_contact(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    client_id: uuid.UUID,
    full_name: str,
    email: str | None,
    phone: str | None,
    title: str | None,
    is_primary: bool,
) -> Contact:
    set_org_context(db, org_id)
    client = queries.get_client(db, org_id, client_id)
    if client is None:
        raise NotFound("Client not found")
    if client.archived_at is not None:
        raise Conflict("Cannot add a contact to an archived client", code="client_archived")

    if is_primary:
        _unset_existing_primary_contact(db, org_id, client_id)

    contact = Contact(
        org_id=org_id, client_id=client_id, full_name=full_name, email=email,
        phone=phone, title=title, is_primary=is_primary,
    )  # fmt: skip
    db.add(contact)
    db.flush()
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="contact.created",
        entity_type="contact", entity_id=contact.id, data={"client_id": str(client_id)},
    )  # fmt: skip
    db.commit()
    return contact


def _unset_existing_primary_contact(db: Session, org_id: uuid.UUID, client_id: uuid.UUID) -> None:
    """Flush is required before the caller inserts/updates a new primary
    contact — otherwise the partial unique index would see two primary rows
    at once mid-transaction and reject the change even though the net result
    is valid."""
    existing = db.scalar(
        select(Contact).where(
            Contact.org_id == org_id, Contact.client_id == client_id, Contact.is_primary.is_(True)
        )
    )
    if existing is not None:
        existing.is_primary = False
        db.flush()


def update_contact(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    contact_id: uuid.UUID,
    full_name: str | None,
    email: str | None,
    phone: str | None,
    title: str | None,
    is_primary: bool | None,
) -> Contact:
    set_org_context(db, org_id)
    contact = queries.get_contact(db, org_id, contact_id)
    if contact is None:
        raise NotFound("Contact not found")

    if is_primary is True and not contact.is_primary:
        _unset_existing_primary_contact(db, org_id, contact.client_id)

    if full_name is not None:
        contact.full_name = full_name
    if email is not None:
        contact.email = email
    if phone is not None:
        contact.phone = phone
    if title is not None:
        contact.title = title
    if is_primary is not None:
        contact.is_primary = is_primary

    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="contact.updated",
        entity_type="contact", entity_id=contact.id,
    )  # fmt: skip
    db.commit()
    return contact


def delete_contact(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID, contact_id: uuid.UUID
) -> None:
    set_org_context(db, org_id)
    contact = queries.get_contact(db, org_id, contact_id)
    if contact is None:
        raise NotFound("Contact not found")
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="contact.deleted",
        entity_type="contact", entity_id=contact.id,
    )  # fmt: skip
    db.delete(contact)
    db.commit()


def create_deal(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    client_id: uuid.UUID,
    title: str,
    description: str | None,
    value_amount: int | None,
    value_currency: str,
    owner_user_id: uuid.UUID | None,
    expected_close_date: date | None,
) -> Deal:
    set_org_context(db, org_id)
    client = queries.get_client(db, org_id, client_id)
    if client is None:
        raise NotFound("Client not found")
    if client.archived_at is not None:
        raise Conflict("Cannot create a deal for an archived client", code="client_archived")

    deal = Deal(
        org_id=org_id, client_id=client_id, title=title, description=description,
        stage="lead", value_amount=value_amount, value_currency=value_currency,
        owner_user_id=owner_user_id or actor_id, expected_close_date=expected_close_date,
    )  # fmt: skip
    db.add(deal)
    db.flush()

    db.add(
        DealStageHistory(
            org_id=org_id, deal_id=deal.id, from_stage=None, to_stage="lead", changed_by=actor_id
        )
    )
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="deal.created",
        entity_type="deal", entity_id=deal.id, data={"client_id": str(client_id), "title": title},
    )  # fmt: skip
    db.commit()
    return deal


def update_deal(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    deal_id: uuid.UUID,
    title: str | None,
    description: str | None,
    value_amount: int | None,
    value_currency: str | None,
    owner_user_id: uuid.UUID | None,
    expected_close_date: date | None,
) -> Deal:
    set_org_context(db, org_id)
    deal = queries.get_deal(db, org_id, deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    if is_terminal(deal.stage):
        raise Conflict("Cannot edit a deal that is already won or lost", code="deal_closed")

    if title is not None:
        deal.title = title
    if description is not None:
        deal.description = description
    if value_amount is not None:
        deal.value_amount = value_amount
    if value_currency is not None:
        deal.value_currency = value_currency
    if owner_user_id is not None:
        deal.owner_user_id = owner_user_id
    if expected_close_date is not None:
        deal.expected_close_date = expected_close_date

    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="deal.updated",
        entity_type="deal", entity_id=deal.id,
    )  # fmt: skip
    db.commit()
    return deal


def set_deal_value(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    deal_id: uuid.UUID,
    value_amount: int,
    commit: bool = True,
) -> Deal:
    """Narrow, dedicated entry point for other modules (proposals, when a
    proposal is accepted) to update a deal's value without reaching into the
    Deal model directly — cross-module calls go through service functions
    only, never another module's ORM objects."""
    set_org_context(db, org_id)
    deal = queries.get_deal(db, org_id, deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    if is_terminal(deal.stage):
        raise Conflict("Cannot edit a deal that is already won or lost", code="deal_closed")

    deal.value_amount = value_amount
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="deal.value_synced",
        entity_type="deal", entity_id=deal.id, data={"value_amount": value_amount},
    )  # fmt: skip
    db.flush()
    if commit:
        db.commit()
    return deal


def change_deal_stage(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    deal_id: uuid.UUID,
    to_stage: str,
    lost_reason: str | None,
    note: str | None,
    commit: bool = True,
) -> Deal:
    if not is_valid_stage(to_stage):
        raise BusinessRuleViolation(f"Invalid stage: {to_stage}", code="invalid_stage")

    set_org_context(db, org_id)
    deal = queries.get_deal(db, org_id, deal_id)
    if deal is None:
        raise NotFound("Deal not found")

    if not can_transition(deal.stage, to_stage):
        raise Conflict(
            f"Cannot move a deal from '{deal.stage}' to '{to_stage}'",
            code="invalid_stage_transition",
        )
    if to_stage == "won" and not (deal.value_amount and deal.value_amount > 0):
        raise BusinessRuleViolation(
            "A deal must have a value greater than zero before it can be won",
            code="won_requires_value",
        )
    if to_stage == "lost" and not lost_reason:
        raise BusinessRuleViolation(
            "lost_reason is required when losing a deal", code="lost_requires_reason"
        )

    from_stage = deal.stage
    deal.stage = to_stage
    if to_stage == "lost":
        deal.lost_reason = lost_reason
    if is_terminal(to_stage):
        deal.closed_at = utcnow()

    db.add(
        DealStageHistory(
            org_id=org_id, deal_id=deal.id, from_stage=from_stage, to_stage=to_stage,
            changed_by=actor_id, note=note,
        )
    )  # fmt: skip
    record_audit(
        db, org_id=org_id, actor_user_id=actor_id, action="deal.stage_changed",
        entity_type="deal", entity_id=deal.id, data={"from": from_stage, "to": to_stage},
    )  # fmt: skip
    db.flush()
    if commit:
        db.commit()
    return deal
