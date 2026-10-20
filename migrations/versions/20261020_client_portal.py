"""client portal account links

Revision ID: clientportal01
Revises: passwordreset01
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "clientportal01"
down_revision = "passwordreset01"
branch_labels = None
depends_on = None

_APP_ROLE = "agencyos_app"


def upgrade() -> None:
    op.add_column("users", sa.Column("client_id", sa.Uuid(), nullable=True))
    op.add_column("invites", sa.Column("client_id", sa.Uuid(), nullable=True))

    op.create_foreign_key(
        "fk_users_org_id_clients",
        "users",
        "clients",
        ["org_id", "client_id"],
        ["org_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_invites_org_id_clients",
        "invites",
        "clients",
        ["org_id", "client_id"],
        ["org_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_users_org_id_client_id", "users", ["org_id", "client_id"])
    op.create_index("ix_invites_org_id_client_id", "invites", ["org_id", "client_id"])


def downgrade() -> None:
    op.drop_index("ix_invites_org_id_client_id", table_name="invites")
    op.drop_index("ix_users_org_id_client_id", table_name="users")
    op.drop_constraint("fk_invites_org_id_clients", "invites", type_="foreignkey")
    op.drop_constraint("fk_users_org_id_clients", "users", type_="foreignkey")
    op.drop_column("invites", "client_id")
    op.drop_column("users", "client_id")
