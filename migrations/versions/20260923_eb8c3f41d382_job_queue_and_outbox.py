"""job queue and outbox

Revision ID: eb8c3f41d382
Revises: de6c97bd7249
Create Date: 2026-09-23

A Postgres-native job queue implementing the transactional outbox pattern, no
external broker (no Redis/RabbitMQ/Celery). Two pieces:

1. `jobs` table — every row is a unit of work. `app.platform.jobs.enqueue()` is
   called from WITHIN an existing business transaction (e.g. inside
   service.create_invite, before its own commit), so a job is durably queued if
   and only if the business change it belongs to actually committed. That
   atomicity guarantee, without a separate message broker or two-phase commit,
   is the entire point of the outbox pattern.

2. `claim_jobs()` — a single `UPDATE ... FROM (SELECT ... FOR UPDATE SKIP
   LOCKED)` statement. SKIP LOCKED lets N concurrent workers each grab a
   disjoint batch of rows without blocking on each other's locks and without
   ever claiming the same row twice — the classic safe pattern for a
   multi-worker queue on a plain relational table.

This table deliberately has NO Row-Level Security: the whole point of a
background worker is that it processes jobs across every tenant, so it must
see all of them. Application code enqueues jobs only from within request-scoped
code that has already gone through normal RLS-protected reads/writes to decide
what belongs in the job — the job table itself is trusted internal
infrastructure, the same category as rate_limit_buckets.
"""

from alembic import op

revision = "eb8c3f41d382"
down_revision = "de6c97bd7249"
branch_labels = None
depends_on = None

_APP_ROLE = "agencyos_app"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NULL,
            job_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'dead_letter')),
            attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts INT NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
            run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_error TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Partial index: only pending/processing rows are ever scanned by a claim —
    # completed/failed/dead_letter rows accumulate but never slow down claiming.
    op.execute("""
        CREATE INDEX ix_jobs_claimable ON jobs (run_after)
        WHERE status IN ('pending', 'processing')
    """)
    op.execute("CREATE INDEX ix_jobs_org_id ON jobs (org_id)")

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON jobs TO {_APP_ROLE}")

    op.execute("""
        CREATE FUNCTION claim_jobs(p_limit INT, p_stale_after_seconds INT DEFAULT 300)
        RETURNS SETOF jobs
        LANGUAGE sql AS $$
            UPDATE jobs SET status = 'processing', updated_at = now()
            WHERE id IN (
                SELECT id FROM jobs
                WHERE (status = 'pending' AND run_after <= now())
                   -- Reclaim jobs a crashed/hung worker never finished (no
                   -- heartbeat needed — staleness IS the heartbeat check).
                   OR (status = 'processing'
                       AND updated_at <= now() - make_interval(secs => p_stale_after_seconds))
                ORDER BY run_after
                FOR UPDATE SKIP LOCKED
                LIMIT p_limit
            )
            RETURNING *
        $$
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION claim_jobs(INT, INT) TO {_APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS claim_jobs(INT, INT)")
    op.execute(f"REVOKE ALL ON jobs FROM {_APP_ROLE}")
    op.execute("DROP TABLE IF EXISTS jobs")
