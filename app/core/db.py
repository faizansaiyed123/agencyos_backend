"""Database engine/session plumbing and the tenant-context helpers.

Tenant isolation works in two layers:
  1. Application code always filters by org where it matters.
  2. PostgreSQL Row-Level Security refuses to show or write rows of another org.
The RLS layer reads `app.org_id`, which we set with SET LOCAL semantics
(`set_config(..., is_local => true)`), so it lives and dies with the transaction.
"""

import uuid
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    # expire_on_commit=False: an explicit commit ends the transaction (and with it the
    # RLS context), so we must not lazily reload objects afterwards.
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request. Endpoints commit explicitly."""
    with get_sessionmaker()() as session:
        yield session


def set_org_context(db: Session, org_id: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.org_id', :v, true)"), {"v": str(org_id)})


def set_lookup_key(db: Session, key: str) -> None:
    """Narrow, transaction-local exception used only for pre-authentication lookups
    (find a user by email, a refresh/invite token by hash) before the org is known."""
    db.execute(text("SELECT set_config('app.lookup_key', :v, true)"), {"v": key})
