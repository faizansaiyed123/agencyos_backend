# Current Verified Project Checkpoint — 2026-10-20

This file contained historical implementation notes. The current verified state is maintained in:
- `PROJECT_STATUS.md`
- `IMPLEMENTATION_CHECKLIST.md`
- `ARCHITECTURE_AND_API_MAP.md`
- `KNOWN_ISSUES.md`
- `RECOVERY.md`
- `FEATURE_ROADMAP.md`

Since the historical notes below were written, the source has been re-audited and additional work has been implemented, including refresh-token concurrency hardening, atomic proposal acceptance, serialized idempotency for invite/payment workflows, password recovery, SMTP email delivery, frontend resilience, regression tests, and CI workflows. Do not use older statements below as proof that current tests or deployments were executed.

---

# AgencyOS — Progress

State as of this session. Read this first in any new session before writing code;
it is the source of truth for what's done vs. not, ahead of memory summaries.

## THE BACKEND-COMPLETE GATE — read this before saying "backend is complete"
**Status 2026-10-15: every domain is ✅ except AI/RAG (⚠️ keyword search only; see its row). All gates green: ruff, ruff format, mypy --strict (93 files), import-linter (3 contracts), 140 tests on real Postgres, plus a live uvicorn+worker end-to-end run.**

The user has explicitly required: the backend is NOT complete until every
domain below is implemented, tested against real Postgres, passing all 5
gates, AND verified end-to-end — not "the code exists," not "the happy path
works." "Backend is fully complete" is a sentence I am only allowed to say
once every row below is ✅, and I must re-audit this table honestly at the
start of that claim, not assume a stale ✅ is still true.

| Domain | Status | Notes / evidence |
|---|---|---|
| Identity/Auth (users, orgs, roles, MFA, sessions) | ✅ | test_identity_api.py, test_mfa.py |
| Platform infra (audit, jobs/outbox, rate limit, idempotency) | ✅ | test_jobs.py, test_rate_limit.py, test_idempotency.py (concurrency-proven) |
| CRM (clients, contacts, deals, pipeline) | ✅ | test_crm.py, test_deal_states.py |
| Proposals (priced scope, deal→won, **→ project on accept**) | ✅ | test_proposals.py, test_proposal_states.py; conversion in test_projects.py |
| Projects (milestones, tasks, team, rates) | ✅ | test_projects.py: conversion idempotent per deal, lifecycle rules, team-member scoping, tenant isolation |
| Time tracking (timer, entries, approval, rate snapshot) | ✅ | test_time.py incl. 4-thread concurrent timer start (partial unique index) |
| Billing (invoices, lines, payments, numbering, void) | ✅ | test_billing.py incl. concurrent gapless numbering (8 threads), concurrent payments cannot overpay, DB CHECK backstops, idempotent payments |
| Collaboration (comments, @mentions, approvals, notifications) | ✅ | test_collab.py |
| Real-time notifications (SSE via LISTEN/NOTIFY) | ✅ | test_collab.py (per-user filtering, purpose-bound ticket) **and verified live** against uvicorn with curl |
| Files (attachments, storage) | ✅ | test_files.py: allow-list, magic bytes, size cap, name sanitising, nosniff/attachment, access control; multipart verified live |
| Reporting (overview, attention feed, revenue, pipeline, utilization, project health) | ✅ | test_reporting_search.py |
| Webhooks (HMAC-signed, retried, SSRF-guarded) | ✅ | test_webhooks.py + test_worker_registration.py |
| GDPR export/erasure | ✅ | test_privacy.py (anonymise, retained-records list, last-owner guard) |
| Feature flags | ✅ | test_flags.py (per-org, stable monotonic rollout) |
| OpenTelemetry tracing | ✅ | test_tracing.py (route-template span names, traceparent continuation); off by default |
| AI/RAG (semantic search, AI assistant) | ⚠️ PARTIAL | **Built:** Postgres full-text search (stemming, ranking, snippets, permission-scoped) and a keyword assistant that routes intents to the reports and otherwise returns real matching rows (never generates text). **NOT built:** self-hosted embeddings + pgvector semantic search. It needs a model download (Hugging Face) and the pgvector extension, neither available in the build sandbox. The adapter seam is app/modules/search/service.py (`search`, `ask`). Do not call the backend "fully complete" while this row is ⚠️. |

Update this table's status in the SAME commit as the work that changes it —
never let it go stale. When a domain is marked ✅, the commit message and this
file must say what test evidence backs that (test file names, concurrency
tests run, all 5 gates green) — "implemented" alone is not evidence.

## Environment (sandbox-specific, recreate each session)
- Postgres 16 installed via apt, cluster `main` on port 5432.
- Roles: `agencyos` (schema owner, superuser locally, password `agencyos`),
  `agencyos_app` (runtime role, NOSUPERUSER NOBYPASSRLS, password `agencyos_app`).
- Databases: `agencyos` (dev), `agencyos_test`.
- Helper script `backend/scripts/ensure_local_pg.sh` recreates all of the above
  idempotently — run it first in any new session (Postgres does NOT stay running
  between sessions).
- Python venv at `/home/claude/venv`; backend deps installed there (see
  `backend/pyproject.toml`, extras include `pyotp`, `cryptography`, `qrcode`,
  `types-qrcode`). Recreate with
  `python3 -m venv /home/claude/venv && /home/claude/venv/bin/pip install -e backend[dev]`
  if the venv is gone.
- **Sandbox quirk**: background processes (`uvicorn &`) do NOT survive between
  separate tool calls in this container — each call is an isolated shell. Any
  live-server test (start + curl) must happen inside ONE bash call. `-1` return
  codes from the tool are sometimes transient sandbox flakiness, not real
  failures — check actual stdout content before concluding a command failed.
- **This whole container is ephemeral per conversation.** Nothing here survives
  between chat sessions on its own. The backend code lives in
  `/home/claude/agencyos/backend` with a real git history (`git log` to see it).
  At the end of a session, zip and present the repo (including `.git/`) via
  present_files so the user can download it, and ask them to re-upload the zip at
  the start of the next session — unzip it back to
  `/home/claude/agencyos/backend` before doing anything else. My own memory
  (`/areas/agencyos.md`) only holds durable user-stated decisions, not code state.
- When a migration written earlier IN THE SAME uncommitted session turns out to
  be wrong, it's fine to edit it in place and re-apply (downgrade/upgrade, or
  drop+recreate the two local databases from scratch if migration state gets
  confused) — nothing has been "shipped" until it's committed. Once committed,
  switch to forward-only corrective migrations instead.

## Repo layout
`/home/claude/agencyos/backend/` — the FastAPI backend, a real git repo.

## Definition of "done" for a module (apply this to every module going forward)
A module isn't done until all five of these are clean, in this order:
1. `ruff format .`
2. `ruff check .`
3. `mypy app` (strict)
4. `lint-imports` (import-linter — module boundaries)
5. `pytest tests/ -q` against real Postgres (not sqlite, not mocks) — covering the
   happy path, the documented business rules/invariants, and at least one
   deliberate cross-tenant/IDOR attempt per module that exposes user-facing data.
   For anything claiming to be race-safe (rate limiting, sequence numbering,
   idempotent creation), add an actual concurrent-threads stress test proving it
   — not just a sequential test, which can't catch a read-then-write race.

## Done — identity module core (auth, invites, RLS tenant isolation)
- Architecture: modular monolith, function-based business logic, sync
  SQLAlchemy 2.0, Postgres RLS + composite tenant FKs, JWT access token +
  rotating refresh-token-in-cookie auth.
- `app/core/`: config (pydantic-settings, prod guards for JWT_SECRET and
  MFA_ENCRYPTION_KEY), db (session + RLS context setters), security (argon2id,
  JWT access + mfa_pending tokens, opaque tokens), crypto (Fernet at-rest
  encryption for TOTP secrets), errors (RFC 9457 problem+json, global
  handlers), logging (structlog), pagination, permissions (role/perm matrix),
  auth (generic bearer-token/refresh-cookie extraction ONLY — no model
  knowledge, see architecture note below), models (Base, naming convention).
- `app/modules/identity/`: models (Organization, User, RefreshToken, Invite,
  MfaRecoveryCode), schemas, queries, service (signup, authenticate incl. MFA
  branching, refresh rotation + theft detection, invite create/accept/revoke,
  role change with last-owner protection, MFA enroll/confirm/verify/disable),
  mfa.py (pure TOTP helpers — secret gen, QR/SVG, code verify, recovery
  codes), deps (current_user/CurrentUser/require/require_role — live HERE not
  in core, see architecture note), router (all endpoints under /api/v1).
- `app/platform/`: audit.py (append-only audit_log), email.py (console/memory
  stub), idempotency.py (Idempotency-Key support, RLS-protected table),
  rate_limit.py (atomic Postgres sliding-window limiter, no Redis), jobs.py
  (Postgres job queue + transactional outbox, no Redis/Celery).
- Three Alembic migrations beyond the initial schema: `658314d016fd` (RLS +
  grants, incl. `app_current_org_id()`/`app_current_lookup_key()` helpers),
  `de6c97bd7249` (MFA columns + recovery codes, idempotency_keys table,
  rate_limit_buckets table + `rate_limit_hit()` plpgsql function),
  `eb8c3f41d382` (jobs table + `claim_jobs()` plpgsql function).
- `main.py`: request-id middleware, structured logging, CORS, /healthz,
  /readyz, error handlers, identity router mounted at /api/v1, job handlers
  registered at startup. `worker.py`: standalone job-worker process entrypoint.
- `tests/`: conftest.py (real-Postgres fixtures, TRUNCATE between tests incl.
  rate_limit_buckets and jobs) + test_identity_api.py (17) + test_mfa.py (9)
  + test_idempotency.py (3) + test_rate_limit.py (4) + test_jobs.py (5) =
  **38 tests, all green**.
- All 5 gates green: `ruff format`, `ruff check`, `mypy --strict`,
  `lint-imports`, `pytest` (38/38).

### Advanced features added (interview-differentiator pass — user explicitly
### asked for engineering depth beyond basic CRUD; see roadmap below for what's
### still queued)
- **TOTP MFA** (RFC 6238, works with any standard authenticator app — no
  third-party service): enroll generates a secret + QR (SVG, no Pillow dep)
  but does NOT enable MFA; confirm requires a real code first. Login branches
  on `mfa_enabled`: correct password alone issues a short-lived `mfa_pending`
  JWT (distinct `typ` claim — structurally can never be accepted as a real
  access token) instead of real tokens; `POST /auth/mfa/verify` exchanges
  that + a TOTP or recovery code for the actual session. 10 single-use
  recovery codes, hashed at rest, shown once. Disabling MFA requires BOTH the
  current password AND a valid second factor (a stolen live session alone
  can't turn it off). DB check constraint
  `mfa_enabled = false OR mfa_secret_encrypted IS NOT NULL` backs the
  invariant even against an application bug.
- **Idempotency-Key support** (Stripe-style), applied to `POST /invites`:
  replaying the same key + same body returns the ORIGINAL cached response
  (proven by asserting the exact same invite id comes back); same key +
  different body → 409. Skipping the key on a retry demonstrably creates
  duplicate-side-effect churn (test asserts this) — the point of the feature.
- **Atomic Postgres rate limiting, no Redis**: `rate_limit_hit()` is a single
  plpgsql UPSERT whose SET clause reads the row's own current value to decide
  reset-vs-increment, so Postgres's row lock makes it race-free under
  concurrency. Proven, not asserted: a 50-way concurrent stress test against a
  limit of 10 allows exactly 10, not more. Wired into login (by IP AND by
  normalized email — two independent limits) and signup (by IP).
- **Postgres-native job queue + transactional outbox, no Redis/Celery**
  (`app/platform/jobs.py`, migration `eb8c3f41d382`, worker entrypoint
  `app/worker.py`): `claim_jobs()` is a single
  `UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED)` statement so N
  concurrent workers each claim a disjoint batch with zero coordination and
  zero double-claims — proven with a 10-worker/100-job stress test, not just
  sequential logic. Stale `processing` jobs (crashed worker) self-heal via a
  staleness check, no separate heartbeat needed. Exponential backoff (capped
  1h) up to `max_attempts`, then `dead_letter`. `enqueue()` takes no commit of
  its own — it's called from inside an existing business transaction (wired
  into `identity.service.create_invite`, right before its own commit), so a
  job exists if and only if the business change it belongs to actually
  committed. Demonstrated end-to-end, not just described: invite creation now
  really enqueues a `send_invite_email` job, and a test runs the worker and
  confirms the email backend actually received it.

### Architecture note: core vs. modules for auth
`app/core/auth.py` intentionally holds ONLY generic, model-free FastAPI
dependencies (`bearer_token`, `refresh_token_cookie`) — no import of `User` or
any other module's model. The actual `current_user` dependency lives in
`app/modules/identity/deps.py`. `app.core` must never import `app.modules.*`,
but other future modules (crm, projects, ...) SHOULD import
`CurrentUser`/`require`/`require_role` from `app.modules.identity.deps` —
that's a one-directional, expected dependency, not a cycle.

## Bugs found and fixed (don't reintroduce)
1. **RLS ordering in signup**: `organizations` row was inserted before
   `set_org_context` was called, so the WITH CHECK policy rejected it. Fixed by
   generating the org UUID client-side and setting context before insert.
   **General rule: any INSERT into a tenant-scoped table must have
   `set_org_context` called earlier in the SAME transaction.**
2. **Pooled-connection empty-string GUC bug**: once a custom GUC (`app.org_id`,
   `app.lookup_key`) has been set via `SET LOCAL` on a connection, it reverts to
   `''` after the transaction ends, not `NULL`. Casting `''::uuid` raises
   instead of just not matching — a near-certain crash under real pooled
   traffic. Fixed with `app_current_org_id()`/`app_current_lookup_key()` SQL
   helpers using `NULLIF(current_setting(...), '')`. **Any new RLS policy must
   use these helpers, never inline `current_setting(...)::uuid` casts.**
3. **Missing sequence grant**: BIGSERIAL columns need their own
   `GRANT USAGE, SELECT ON SEQUENCES` — table grants alone don't cover it. An
   `ALTER DEFAULT PRIVILEGES` clause covers future sequences automatically.
4. **core/modules layering violation**: `app/core/auth.py` originally imported
   `app.modules.identity.models.User`, caught by `lint-imports`. Fixed by
   splitting into core (model-free) + identity/deps.py (model-aware).
5. **Idempotency writes needed their own `set_org_context` call**: the same
   RLS-ordering bug class as #1, but one level removed — the invite's own
   `service.create_invite` call already commits (ending its transaction and
   resetting the session's RLS context) before the router tries to write the
   idempotency record in a fresh transaction. Fixed by making
   `check_idempotency_key`/`store_idempotency_result` each call
   `set_org_context` themselves rather than assuming the caller already did.
   **General rule: any platform/service function that writes to an RLS table
   must be self-contained about setting org context — never assume an earlier
   call in the same request already left it set, because a `db.commit()`
   anywhere in between resets it.**
6. **First MFA check constraint was too strict**: required
   `(mfa_enabled=false AND secret IS NULL) OR (mfa_enabled=true AND secret IS
   NOT NULL)`, which is a biconditional — but "enrolling, secret generated,
   not yet confirmed" (`mfa_enabled=false`, secret NOT NULL) is a legitimate
   intermediate state. Fixed to the one-directional
   `mfa_enabled = false OR mfa_secret_encrypted IS NOT NULL`.
7. **Missing `eager_defaults=True` on `Base` (systemic, affects every model)**:
   `onupdate=func.now()` columns (`updated_at`) can trigger a separate
   post-flush SELECT to refresh their value after an UPDATE. If that SELECT
   happens after `db.commit()` — RLS context already reverted — it silently
   returns zero rows, surfacing as a confusing `ObjectDeletedError` instead of
   an RLS error. First hit in CRM's `update_client`/`archive_client`/
   `change_deal_stage`. Fixed once, at the `Base` class
   (`__mapper_args__ = {"eager_defaults": True}`), so every model — present
   and future — is protected, not just the ones that happened to trigger it.
8. **`alembic revision --autogenerate` always proposes dropping `jobs`,
   `rate_limit_buckets`, and `uq_contacts_one_primary_per_client`**: these are
   created via raw SQL (`op.execute`) rather than SQLAlchemy `Table`/`Index`
   objects, so they're invisible to the ORM metadata autogenerate diffs
   against. **Every future autogenerate must be hand-checked for spurious
   `drop_table`/`drop_index` calls on these three before applying — this is
   not a one-time fix, it will keep happening.**
9. **`JobHandler` originally took only `payload`, no `db` session**: fine for
   the first handler (`send_invite_email`, no DB access needed), but the
   proposal-expiry handler needs to look up and update a proposal — which
   needs `set_org_context` and therefore a session. Changed the signature to
   `(payload, db)` project-wide (one existing handler + its test updated) once
   the second handler's real need became clear, rather than guessing the
   right signature up front.
10. **Deal-stage skipping vs. proposal acceptance (a design gap, not a code
    bug)**: the deal pipeline correctly forbids skipping stages, so a fresh
    'lead' deal accepting a proposal couldn't jump straight to 'won'. Fixed by
    adding `deal_states.HAPPY_PATH_ORDER` and walking the deal forward one
    validated stage at a time in `accept_proposal`, recording every
    intermediate transition — not by loosening the state machine's rules.

## Verified working (real Postgres, both by hand and by the pytest suite)
- Full signup → login (incl. MFA branch) → refresh (rotation) → invite →
  accept → role-change chain.
- Full CRM chain: client → contact (incl. primary-contact swap) → deal →
  every pipeline stage transition (incl. rejection of invalid/skipped
  transitions) → archive (blocked while deals are open).
- Full Proposals chain: create → add/edit/remove line items (draft-only) →
  send (blocked with no items) → accept (deal walks forward to 'won',
  value synced, full history recorded) or reject (requires a reason, deal
  untouched) → delayed per-proposal expiry job (both directions: an overdue
  proposal actually expires; an already-accepted one is NOT overwritten by a
  late-running expiry job — a real race condition, handled, not assumed away).
- **Tenant isolation, both layers, confirmed independently, across every
  module added so far**: app level (org B's token/queries never see org A's
  clients/deals/proposals; IDOR attempts → 404) and raw RLS level (connecting
  directly as `agencyos_app`: zero rows with no org context; only matching
  org's rows with context set; context correctly reverts to no-access after
  COMMIT on the same session).
- **Rate-limit atomicity under real concurrency** (not just sequential logic):
  50 threads hitting a limit-10 bucket simultaneously → exactly 10 allowed.
- **Job-queue atomicity under real concurrency**: 10 threads racing to claim
  from a pool of 100 jobs → zero double-claims, all 100 claimed exactly once.

## Known deferred work (not a bug — a deliberate two-step build)
- The brief's full workflow is "accepting a proposal creates the project,
  milestones and budget in one transaction, idempotently." Right now
  `accept_proposal` only does the deal→won half — project creation doesn't
  exist yet because the Projects module doesn't exist yet. **When building
  Projects, come back to `proposals/service.py::accept_proposal` and extend it
  to also call a new `projects.service.create_project_from_deal(...)` in the
  same transaction** (idempotent — a second call for an already-converted
  deal should return the existing project, not error or duplicate).

## Not yet done — pick up here

### Immediate next (advanced-features roadmap, user explicitly asked for
### interview-differentiating depth — this is a standing priority, not a
### one-off; keep proposing/building items like these alongside normal
### module work, not only when asked)
1. **Real-time notifications via Postgres LISTEN/NOTIFY → Server-Sent
   Events** — event-driven, no WebSocket infra, no third-party pub/sub. The
   job queue's `jobs` table is a natural trigger source (NOTIFY on insert) if
   we want the worker to react instantly instead of polling, too — worth
   doing both at once.
2. **Outgoing webhooks with HMAC signing + exponential-backoff retry** — a
   feature OF the product (agency's own systems subscribe to AgencyOS
   events), not a dependency ON a third party. Natural fit ON TOP of the job
   queue: enqueue a `deliver_webhook` job per subscriber per event, reusing
   the same retry/backoff/dead-letter machinery `jobs.py` already has.
3. **GDPR-style data export + right-to-erasure endpoint** — real production
   maturity signal, and directly reuses the audit-log/RLS infrastructure
   already in place.
4. **Feature flags via a DB table** — progressive delivery, self-hosted,
   small but a real signal of production maturity.
5. **OpenTelemetry tracing with a console/local exporter** — zero external
   service, observability signal.
6. As each of these lands, add its own concurrency/adversarial test in the
   style of the rate-limiter and job-queue stress tests — sequential-only
   tests are not sufficient proof for anything claiming to be safe under
   concurrency.

### Core build order (unchanged from Phase 1) — CRM and Proposals now done
7. **Projects module** is next: milestones, tasks, team assignment. When
   built, extend `proposals/service.py::accept_proposal` per "Known deferred
   work" above to actually create the project on acceptance. Then: time
   tracking, billing (invoices/payments — the hardest module per Phase 1,
   gets the most tests), collaboration (comments/approvals/notifications),
   files, reporting/attention-feed, in that order — see `/areas/agencyos.md`
   in my memory for the full original design if any of this needs
   re-deriving.
8. As each new business module lands, add an import-linter "layers" contract
   (comment already in pyproject.toml) so e.g. `crm` can depend on `identity`
   but not vice versa, and sibling modules don't reach into each other's
   models directly.
9. No CI config yet. Worth adding once there's a git remote to push to.
10. Frontend not started — correctly, per the build order (backend fully done
    and tested first) and per the user's explicit instruction: do not start
    the frontend, and do not declare the backend complete, until every row in
    THE BACKEND-COMPLETE GATE table at the top of this file is ✅ with real
    test evidence — re-audit that table honestly, don't assume a stale ✅.


## Session log — 2026-10-15 (remaining backend build)
- Added: projects, time, billing, collab (+SSE), files, reporting, search/assistant, privacy, flags,
  webhooks, tracing. Migrations a1projects01, a2timebilling, a3collabfiles (hand-cleaned autogenerate:
  always delete the false-positive drops of `jobs`, `rate_limit_buckets`, uq_contacts_one_primary_per_client).
- **Bug found only by the live run**: app/worker.py did not register the webhook handler, so webhook jobs
  would dead-letter in production. Fixed + tests/test_worker_registration.py (fresh interpreter).
- **Bug found by tests**: SUM(bigint) returned numeric → money serialised as a JSON *string*. Reporting
  helpers now convert integral Decimals to int.
- Layering contract added to pyproject (identity < crm < projects < proposals < time < billing < collab
  < files < reporting < search|privacy; platform may not import business modules).
- Operational: run TWO processes — `uvicorn app.main:app` and `python -m app.worker`. Without the worker,
  invite emails and webhooks are never sent.
- Known limits (deliberate, documented): payments are immutable (no refund/credit-note model yet);
  invoice PDF rendering and invoice emailing are not implemented (data + events are); the client portal
  role has no permissions yet; file storage is local disk behind a `Storage` interface (S3 adapter TBD).
