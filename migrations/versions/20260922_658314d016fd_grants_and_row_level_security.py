"""grants and row level security

Revision ID: 658314d016fd
Revises: 1cd7d03cabb3
Create Date: 2026-09-22

Tenant isolation, layer 2. The application connects as `agencyos_app`, a role
with NO table ownership and NOBYPASSRLS. Every tenant-scoped table gets a
FORCE ROW LEVEL SECURITY policy comparing `org_id` to the session GUC
`app.org_id`, which the app sets per-request via `SET LOCAL` (see
app.core.db.set_org_context). A session that has not set `app.org_id` sees
no rows at all, which is the fail-closed default we want.

Casting the GUC is done through the `app_current_org_id()` helper below rather
than inline `current_setting('app.org_id', true)::uuid`. This matters on a
pooled connection: once a custom GUC has been set via SET LOCAL at least once,
Postgres registers a session-level placeholder for it, and after the
transaction ends the value reverts to '' (empty string), not NULL. Casting ''
to uuid raises an error instead of just failing to match, which would take
down every request on a connection that happens to be reused after a prior
request set the org context. The helper treats '' the same as unset.

`users` additionally needs an *unscoped* lookup path for login, before the
caller's org is known: a narrow policy permits SELECT when the row's email
matches a transaction-local `app.lookup_key` GUC. Nothing else about the row
is exposed by that path since the same row-level policy still applies to
UPDATE/DELETE.

This migration also grants the minimum verbs `agencyos_app` needs. It gets
no privileges on `alembic_version` and cannot alter schema.
"""

from alembic import op

revision = "658314d016fd"
down_revision = "1cd7d03cabb3"
branch_labels = None
depends_on = None

_TENANT_TABLES = ("organizations", "users", "invites", "refresh_tokens", "audit_log")

_APP_ROLE = "agencyos_app"


def upgrade() -> None:
    # STABLE (not IMMUTABLE): it reads a GUC that can change within a session.
    # SECURITY INVOKER (the default) is fine; it does not need elevated rights.
    op.execute("""
        CREATE FUNCTION app_current_org_id() RETURNS uuid AS $$
            SELECT NULLIF(current_setting('app.org_id', true), '')::uuid
        $$ LANGUAGE sql STABLE
    """)
    op.execute("""
        CREATE FUNCTION app_current_lookup_key() RETURNS text AS $$
            SELECT NULLIF(current_setting('app.lookup_key', true), '')
        $$ LANGUAGE sql STABLE
    """)

    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
    # Auto-increment columns (audit_log.id) are backed by a sequence, which needs its
    # own USAGE grant independent of the table grant. The ALTER DEFAULT PRIVILEGES
    # clause covers sequences created by future migrations too, so this isn't a trap
    # someone has to remember to repeat.
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE agencyos IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {_APP_ROLE}"
    )
    for table in _TENANT_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {_APP_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # audit_log: append-only for the app role. No UPDATE/DELETE grant at all, so a bug
    # (or an attacker with app-level SQL injection) cannot rewrite history.
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {_APP_ROLE}")

    # organizations has no org_id column of its own; scope on its own id.
    op.execute("""
        CREATE POLICY tenant_isolation ON organizations
        USING (id = app_current_org_id())
        WITH CHECK (id = app_current_org_id())
    """)

    for table in ("users", "invites", "refresh_tokens", "audit_log"):
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (org_id = app_current_org_id())
            WITH CHECK (org_id = app_current_org_id())
        """)

    # Pre-auth login lookup: allow finding a user by email (case-insensitive) across
    # orgs, but ONLY a SELECT, and ONLY when app.lookup_key was explicitly set for this
    # transaction (see app.core.db.set_lookup_key). This does not weaken UPDATE/DELETE,
    # which still require the row's own tenant_isolation policy to also pass.
    op.execute("""
        CREATE POLICY login_lookup ON users
        FOR SELECT
        USING (lower(email) = lower(app_current_lookup_key()))
    """)

    # Same idea for redeeming an invite/refresh token by its hash before org_id is known.
    op.execute("""
        CREATE POLICY token_lookup ON invites
        FOR SELECT
        USING (token_hash = app_current_lookup_key())
    """)
    op.execute("""
        CREATE POLICY token_lookup ON refresh_tokens
        FOR SELECT
        USING (token_hash = app_current_lookup_key())
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS token_lookup ON refresh_tokens")
    op.execute("DROP POLICY IF EXISTS token_lookup ON invites")
    op.execute("DROP POLICY IF EXISTS login_lookup ON users")
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM {_APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE agencyos IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {_APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE}")
    op.execute("DROP FUNCTION IF EXISTS app_current_lookup_key()")
    op.execute("DROP FUNCTION IF EXISTS app_current_org_id()")
