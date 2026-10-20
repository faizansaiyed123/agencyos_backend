"""mfa idempotency rate limiting

Revision ID: de6c97bd7249
Revises: 658314d016fd
Create Date: 2026-09-22

Adds three independent capabilities:
  1. TOTP MFA columns on users + a recovery-codes table (tenant-scoped, RLS'd
     like everything else — uses app_current_org_id() from the prior migration).
  2. Idempotency-Key support (tenant-scoped, RLS'd) for mutating endpoints.
  3. A Postgres-native sliding-window rate limiter: a plain table plus a single
     atomic UPSERT function (`rate_limit_hit`). This table is deliberately NOT
     tenant-scoped or RLS-protected — it's used pre-auth (login/signup, keyed by
     IP or email) and holds no tenant data, only opaque counters.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "de6c97bd7249"
down_revision = "658314d016fd"
branch_labels = None
depends_on = None

_APP_ROLE = "agencyos_app"
_NEW_TENANT_TABLES = ("mfa_recovery_codes", "idempotency_keys")


def upgrade() -> None:
    # --- MFA columns + recovery codes -------------------------------------
    op.add_column(
        "users",
        sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("users", sa.Column("mfa_secret_encrypted", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "mfa_secret_present_when_enabled",
        "users",
        "mfa_enabled = false OR mfa_secret_encrypted IS NOT NULL",
    )

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"],
            name="fk_mfa_recovery_codes_org_id_users", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mfa_recovery_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_mfa_recovery_codes_code_hash")),
    )  # fmt: skip
    op.create_index(
        "ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"], unique=False
    )

    # --- Idempotency keys ---------------------------------------------------
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"],
            name="fk_idempotency_keys_org_id_users", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("org_id", "key", name="uq_idempotency_keys_org_id_key"),
    )  # fmt: skip

    # --- RLS + grants for the two new tenant tables, matching the pattern from
    # the prior migration (app_current_org_id() helper, FORCE ROW LEVEL SECURITY).
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")
    for table in _NEW_TENANT_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {_APP_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (org_id = app_current_org_id())
            WITH CHECK (org_id = app_current_org_id())
        """)
    # Recovery codes are never updated once issued (only marked used_at, which IS
    # an update — so no extra restriction needed beyond tenant_isolation). Kept
    # here for symmetry with audit_log's comment style: nothing to restrict.

    # --- Rate limiting: plain table + one atomic function, no RLS -----------
    op.execute("""
        CREATE TABLE rate_limit_buckets (
            key TEXT PRIMARY KEY,
            window_start TIMESTAMPTZ NOT NULL,
            count INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON rate_limit_buckets TO {_APP_ROLE}")

    op.execute("""
        CREATE FUNCTION rate_limit_hit(p_key TEXT, p_limit INT, p_window_seconds INT)
        RETURNS TABLE(allowed BOOLEAN, remaining INT, reset_at TIMESTAMPTZ)
        LANGUAGE plpgsql AS $$
        DECLARE
            v_now TIMESTAMPTZ := clock_timestamp();
            v_window_start TIMESTAMPTZ;
            v_count INT;
        BEGIN
            -- Single-statement UPSERT: the row-level lock Postgres takes during
            -- ON CONFLICT makes this atomic under concurrent hits on the same
            -- key, so there is no read-then-write race between check and
            -- increment (the classic bug in hand-rolled rate limiters).
            INSERT INTO rate_limit_buckets (key, window_start, count)
            VALUES (p_key, v_now, 1)
            ON CONFLICT (key) DO UPDATE SET
                window_start = CASE
                    WHEN rate_limit_buckets.window_start <= v_now - make_interval(secs => p_window_seconds)
                    THEN v_now ELSE rate_limit_buckets.window_start
                END,
                count = CASE
                    WHEN rate_limit_buckets.window_start <= v_now - make_interval(secs => p_window_seconds)
                    THEN 1 ELSE rate_limit_buckets.count + 1
                END
            RETURNING rate_limit_buckets.window_start, rate_limit_buckets.count
            INTO v_window_start, v_count;

            RETURN QUERY SELECT
                (v_count <= p_limit),
                GREATEST(p_limit - v_count, 0),
                v_window_start + make_interval(secs => p_window_seconds);
        END;
        $$
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION rate_limit_hit(TEXT, INT, INT) TO {_APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS rate_limit_hit(TEXT, INT, INT)")
    op.execute("DROP TABLE IF EXISTS rate_limit_buckets")

    for table in _NEW_TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {_APP_ROLE}")

    op.drop_table("idempotency_keys")
    op.drop_index("ix_mfa_recovery_codes_user_id", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_constraint("mfa_secret_present_when_enabled", "users", type_="check")
    op.drop_column("users", "mfa_enrolled_at")
    op.drop_column("users", "mfa_secret_encrypted")
    op.drop_column("users", "mfa_enabled")
