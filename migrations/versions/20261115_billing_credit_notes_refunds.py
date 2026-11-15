"""billing credit notes and payment refunds

Revision ID: billingcredits01
Revises: clientportal01
Create Date: 2026-11-15

Credit notes and payment refunds are separate immutable, tenant-scoped ledgers.
The invoice stores transactionally maintained aggregates so settlement status and
balances can be checked by database constraints.
"""

import sqlalchemy as sa
from alembic import op

revision = "billingcredits01"
down_revision = "clientportal01"
branch_labels = None
depends_on = None

_APP_ROLE = "agencyos_app"


def _tenant_policy(table: str, privileges: str) -> None:
    op.execute(f"GRANT {privileges} ON {table} TO {_APP_ROLE}")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (org_id = app_current_org_id())
        WITH CHECK (org_id = app_current_org_id())
    """)


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column(
            "amount_refunded_cents",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "invoices",
        sa.Column(
            "credit_note_cents",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.alter_column("invoices", "amount_refunded_cents", server_default=None)
    op.alter_column("invoices", "credit_note_cents", server_default=None)

    op.drop_constraint(op.f("ck_invoices_status_valid"), "invoices", type_="check")
    op.drop_constraint(op.f("ck_invoices_paid_means_settled"), "invoices", type_="check")
    op.create_check_constraint(
        op.f("ck_invoices_status_valid"),
        "invoices",
        "status IN ('draft', 'sent', 'partially_paid', 'paid', 'credited', 'void')",
    )
    op.create_check_constraint(
        op.f("ck_invoices_paid_means_settled"),
        "invoices",
        "status != 'paid' OR "
        "(amount_paid_cents - amount_refunded_cents >= total_cents - credit_note_cents)",
    )
    op.create_check_constraint(
        op.f("ck_invoices_credited_means_fully_credited"),
        "invoices",
        "status != 'credited' OR credit_note_cents = total_cents",
    )
    op.create_check_constraint(
        op.f("ck_invoices_refunds_within_paid"),
        "invoices",
        "amount_refunded_cents >= 0 AND amount_refunded_cents <= amount_paid_cents",
    )
    op.create_check_constraint(
        op.f("ck_invoices_credits_within_total"),
        "invoices",
        "credit_note_cents >= 0 AND credit_note_cents <= total_cents",
    )

    # The composite key permits refund rows to reference a payment only within
    # the same tenant. The payment's globally unique id remains its primary key.
    op.create_unique_constraint("uq_payments_org_id_id", "payments", ["org_id", "id"])

    op.create_table(
        "credit_note_counters",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "year", name="pk_credit_note_counters"),
    )

    op.create_table(
        "credit_notes",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_credit_notes_amount_positive")),
        sa.ForeignKeyConstraint(
            ["org_id", "invoice_id"],
            ["invoices.org_id", "invoices.id"],
            name="fk_credit_notes_org_id_invoices",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "created_by"],
            ["users.org_id", "users.id"],
            name="fk_credit_notes_org_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credit_notes"),
        sa.UniqueConstraint("org_id", "id", name="uq_credit_notes_org_id_id"),
        sa.UniqueConstraint("org_id", "number", name="uq_credit_notes_org_id_number"),
    )
    op.create_index(
        "ix_credit_notes_org_id_invoice_id",
        "credit_notes",
        ["org_id", "invoice_id"],
        unique=False,
    )

    op.create_table(
        "payment_refunds",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("refunded_on", sa.Date(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_payment_refunds_amount_positive")),
        sa.CheckConstraint(
            "method IN ('bank_transfer', 'card', 'cash', 'other')",
            name=op.f("ck_payment_refunds_method_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "payment_id"],
            ["payments.org_id", "payments.id"],
            name="fk_payment_refunds_org_id_payments",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "created_by"],
            ["users.org_id", "users.id"],
            name="fk_payment_refunds_org_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_refunds"),
    )
    op.create_index(
        "ix_payment_refunds_org_id_payment_id",
        "payment_refunds",
        ["org_id", "payment_id"],
        unique=False,
    )

    # Counters may be advanced by the application; issued financial records
    # are append-only for the runtime role.
    _tenant_policy("credit_note_counters", "SELECT, INSERT, UPDATE")
    _tenant_policy("credit_notes", "SELECT, INSERT")
    _tenant_policy("payment_refunds", "SELECT, INSERT")


def downgrade() -> None:
    for table in ("payment_refunds", "credit_notes", "credit_note_counters"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"REVOKE SELECT, INSERT ON payment_refunds, credit_notes FROM {_APP_ROLE}"
    )
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE ON credit_note_counters FROM {_APP_ROLE}"
    )

    op.drop_index("ix_payment_refunds_org_id_payment_id", table_name="payment_refunds")
    op.drop_table("payment_refunds")
    op.drop_index("ix_credit_notes_org_id_invoice_id", table_name="credit_notes")
    op.drop_table("credit_notes")
    op.drop_table("credit_note_counters")
    op.drop_constraint("uq_payments_org_id_id", "payments", type_="unique")

    op.drop_constraint(op.f("ck_invoices_credits_within_total"), "invoices", type_="check")
    op.drop_constraint(op.f("ck_invoices_refunds_within_paid"), "invoices", type_="check")
    op.drop_constraint(
        op.f("ck_invoices_credited_means_fully_credited"), "invoices", type_="check"
    )
    op.drop_constraint(op.f("ck_invoices_paid_means_settled"), "invoices", type_="check")
    op.drop_constraint(op.f("ck_invoices_status_valid"), "invoices", type_="check")
    op.drop_column("invoices", "credit_note_cents")
    op.drop_column("invoices", "amount_refunded_cents")
    op.create_check_constraint(
        op.f("ck_invoices_status_valid"),
        "invoices",
        "status IN ('draft', 'sent', 'partially_paid', 'paid', 'void')",
    )
    op.create_check_constraint(
        op.f("ck_invoices_paid_means_settled"),
        "invoices",
        "status != 'paid' OR amount_paid_cents = total_cents",
    )
