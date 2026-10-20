"""Declarative base, naming convention and shared column helpers."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Every model's server-evaluated columns (created_at, updated_at, and any
    # future server_default/onupdate column) are fetched via RETURNING in the
    # SAME statement, rather than SQLAlchemy issuing a separate SELECT to
    # refresh them after flush. This matters here specifically: a separate
    # post-flush SELECT runs in whatever RLS context is active AT THAT MOMENT,
    # and if it happens after commit (context reverted) it silently returns
    # zero rows -- surfacing as a confusing ObjectDeletedError, not an RLS
    # error. Forcing eager_defaults=True (rather than leaving it as
    # SQLAlchemy's default "auto") makes this the same guarantee on every
    # model, present and future, instead of something to remember per-column.
    __mapper_args__ = {"eager_defaults": True}


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
