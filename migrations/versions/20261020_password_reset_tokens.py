"""password reset tokens

Revision ID: passwordreset01
Revises: a3collabfiles
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "passwordreset01"
down_revision = "a3collabfiles"
branch_labels = None
depends_on = None

_APP_ROLE = "agencyos_app"


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_password_reset_tokens_org_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_reset_tokens_token_hash")),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"], unique=False
    )
    op.create_index(
        "ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"], unique=False
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON password_reset_tokens TO {_APP_ROLE}")
    op.execute("ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE password_reset_tokens FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON password_reset_tokens
        USING (org_id = app_current_org_id())
        WITH CHECK (org_id = app_current_org_id())
    """)
    op.execute("""
        CREATE POLICY token_lookup ON password_reset_tokens
        FOR SELECT
        USING (token_hash = app_current_lookup_key())
    """)
    # PostgreSQL applies UPDATE policy checks to SELECT ... FOR UPDATE. The lookup
    # transaction has only app.lookup_key before the org is known, so allow the row
    # lock through the same narrowly scoped token lookup; the actual update still
    # requires the tenant org context through WITH CHECK.
    op.execute("""
        CREATE POLICY token_lookup_lock ON password_reset_tokens
        FOR UPDATE
        USING (
            org_id = app_current_org_id()
            OR token_hash = app_current_lookup_key()
        )
        WITH CHECK (org_id = app_current_org_id())
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS token_lookup_lock ON password_reset_tokens")
    op.execute("DROP POLICY IF EXISTS token_lookup ON password_reset_tokens")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON password_reset_tokens")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON password_reset_tokens FROM {_APP_ROLE}")
    op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
