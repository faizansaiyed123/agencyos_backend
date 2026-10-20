"""proposals and proposal items

Revision ID: 7a1156ff9e76
Revises: 9be31241e26b
Create Date: 2026-09-24

Proposals (priced scope sent to a client, linked to a deal) and their line
items. Line items are only mutable while status='draft'
(app.modules.proposals.proposal_states.is_editable) -- enforced in
service.py, not the database, since it depends on the parent row's current
status rather than a static per-row invariant.

RLS follows the established pattern: FORCE ROW LEVEL SECURITY,
tenant_isolation policy using app_current_org_id().

Note: hand-edited after autogenerate to remove THREE false-positive DROP
statements: `jobs` and `rate_limit_buckets` (raw-SQL tables outside ORM
metadata, see eb8c3f41d382 / de6c97bd7249), and
`uq_contacts_one_primary_per_client` (a raw-SQL partial unique index from
9be31241e26b, also outside ORM metadata since Contact.__table_args__ has no
corresponding Index/UniqueConstraint object for it). This will keep
happening on every future autogenerate against these three -- always check
the diff by hand.
"""

import sqlalchemy as sa
from alembic import op

revision = "7a1156ff9e76"
down_revision = "9be31241e26b"
branch_labels = None
depends_on = None

_APP_ROLE = "agencyos_app"
_TENANT_TABLES = ("proposals", "proposal_items")


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status != 'rejected' OR rejection_reason IS NOT NULL", name=op.f("ck_proposals_rejected_requires_reason")),
        sa.CheckConstraint("status IN ('draft', 'sent', 'accepted', 'rejected', 'expired')", name=op.f("ck_proposals_status_valid")),
        sa.ForeignKeyConstraint(["org_id", "client_id"], ["clients.org_id", "clients.id"], name="fk_proposals_org_id_clients", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id", "created_by"], ["users.org_id", "users.id"], name="fk_proposals_org_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id", "deal_id"], ["deals.org_id", "deals.id"], name="fk_proposals_org_id_deals", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposals")),
        sa.UniqueConstraint("org_id", "id", name="uq_proposals_org_id_id"),
    )  # fmt: skip
    op.create_index("ix_proposals_org_id_deal_id", "proposals", ["org_id", "deal_id"], unique=False)
    op.create_index("ix_proposals_org_id_status", "proposals", ["org_id", "status"], unique=False)

    op.create_table(
        "proposal_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("unit_amount", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_proposal_items_quantity_positive")),
        sa.CheckConstraint("unit_amount >= 0", name=op.f("ck_proposal_items_unit_amount_nonneg")),
        sa.ForeignKeyConstraint(["org_id", "proposal_id"], ["proposals.org_id", "proposals.id"], name="fk_proposal_items_org_id_proposals", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_items")),
    )  # fmt: skip
    op.create_index(
        "ix_proposal_items_org_id_proposal_id",
        "proposal_items",
        ["org_id", "proposal_id"],
        unique=False,
    )

    # --- RLS + grants, same pattern as prior migrations ---------------------
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")
    for table in _TENANT_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {_APP_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (org_id = app_current_org_id())
            WITH CHECK (org_id = app_current_org_id())
        """)


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {_APP_ROLE}")

    op.drop_index("ix_proposal_items_org_id_proposal_id", table_name="proposal_items")
    op.drop_table("proposal_items")
    op.drop_index("ix_proposals_org_id_status", table_name="proposals")
    op.drop_index("ix_proposals_org_id_deal_id", table_name="proposals")
    op.drop_table("proposals")
