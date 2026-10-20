from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.models import Base

target_metadata = Base.metadata


def _url() -> str:
    # Tests/CLI may pass -x url=... ; otherwise use the owner connection from settings.
    x = context.get_x_argument(as_dictionary=True)
    return x.get("url") or get_settings().migration_database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
