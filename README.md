# AgencyOS Backend

AgencyOS Backend is a Python 3.12+ FastAPI application backed by PostgreSQL and SQLAlchemy, with Alembic migrations, tenant-aware authorization, PostgreSQL Row-Level Security, background jobs, and separate API and worker processes. The API exposes application routes under `/api/v1`, with health and readiness endpoints at `/healthz` and `/readyz`.

## Key features

- **CRM and deals:** clients, contacts, deals, deal-stage history, and validated deal-stage transitions.
- **Proposals:** proposal and line-item management with draft, sent, accepted, rejected, and expired states.
- **Projects:** projects, members, milestones, tasks, project lifecycle transitions, and project creation from accepted deals.
- **Time tracking:** running timers, manual entries, summaries, entry updates/deletion, and approval.
- **Billing and invoices:** invoices, invoice lines, milestone/time-based billing, payments, invoice numbering, PDF rendering, sending, issuing, and voiding.
- **Client portal:** client-scoped overview, projects, proposals, proposal decisions, invoices, and invoice PDF access.
- **Background worker:** a PostgreSQL-backed job queue and transactional outbox with registered handlers for invite email, password-reset email, proposal expiration, invoice email, and webhook delivery.
- **MFA:** TOTP enrollment and verification, encrypted TOTP secrets, and recovery codes.
- **Webhooks:** tenant-scoped webhook endpoints, signed deliveries, event subscriptions, SSRF protections, retries, and delivery records.

## Architecture

The backend uses:

- Python 3.12+
- FastAPI
- Uvicorn
- SQLAlchemy 2
- PostgreSQL
- Alembic
- Pydantic / pydantic-settings
- Argon2id password hashing
- PyJWT
- PyOTP
- HTTPX
- ReportLab

### Multi-tenancy and security boundaries

Application code applies organization scoping and PostgreSQL Row-Level Security provides a second tenant-isolation boundary. Tenant context is set transaction-locally for database access, and the runtime database role is separate from the schema-owner role.

The backend records audit events in the `audit_log` table. Authentication uses short-lived access tokens and rotating refresh tokens stored in httpOnly cookies. MFA secrets are encrypted at rest.

### State transitions

Business workflows use explicit state-transition functions in dedicated modules. Deal, proposal, project, and invoice lifecycles define allowed transitions and terminal states rather than allowing arbitrary status changes.

## Frontend

The companion frontend repository is:

[agencyos_frontend](https://github.com/faizansaiyed123/agencyos_frontend)

## Quick start

### Docker Compose

The repository includes a PostgreSQL-backed development stack with the API and worker:

```bash
docker compose up --build
```

The backend service runs on port `8000`.

### Local

The project requires Python 3.12 or newer.

Create an environment and install the declared development dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Create `.env` from `.env.example`, then prepare the local PostgreSQL roles and databases:

```bash
bash scripts/ensure_local_pg.sh
```

Apply migrations:

```bash
alembic upgrade head
```

Run the API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run the background worker in a separate process:

```bash
python -m app.worker
```

## Environment variables

The following names are defined in `.env.example`:

```text
AGENCYOS_ENV
AGENCYOS_DATABASE_URL
AGENCYOS_MIGRATION_DATABASE_URL
AGENCYOS_JWT_SECRET
AGENCYOS_CORS_ORIGINS
AGENCYOS_COOKIE_SECURE
AGENCYOS_APP_BASE_URL
AGENCYOS_STORAGE_DIR
AGENCYOS_MAX_UPLOAD_BYTES
AGENCYOS_OTEL_ENABLED
AGENCYOS_OTEL_EXPORTER
AGENCYOS_OTEL_OTLP_ENDPOINT
AGENCYOS_EMAIL_BACKEND
AGENCYOS_SMTP_HOST
AGENCYOS_SMTP_PORT
AGENCYOS_SMTP_USERNAME
AGENCYOS_SMTP_PASSWORD
AGENCYOS_SMTP_FROM_EMAIL
AGENCYOS_SMTP_STARTTLS
AGENCYOS_PASSWORD_RESET_TTL_MINUTES
AGENCYOS_PASSWORD_RESET_RATE_LIMIT_PER_HOUR
```

## Tests

The project uses pytest with `tests/` as the configured test path.

Run:

```bash
pytest
```

The development dependencies also include Ruff, mypy, import-linter, pytest-cov, and related tooling.

## Project structure

```text
app/
  core/                 Configuration, database, security, errors, permissions
  modules/
    billing/            Invoices, payments, PDF generation
    collab/             Comments, approvals, notifications, SSE
    crm/                Clients, contacts, deals
    files/              File assets and storage
    identity/           Authentication, users, invites, MFA, password reset
    portal/             Client portal
    privacy/            Data export and erasure
    projects/           Projects, milestones, members, tasks
    proposals/          Proposals and proposal items
    reporting/          Operational and financial reporting
    search/             Search and assistant endpoints
    time/               Time tracking and approvals
  platform/             Audit, jobs, flags, idempotency, notifications,
                        rate limiting, tracing, and webhooks
  main.py               FastAPI application entrypoint
  worker.py             Background worker entrypoint

migrations/
  versions/             Alembic database migrations

scripts/
  ensure_local_pg.sh    Local PostgreSQL setup
  init_db.sql           Database initialization for Docker Compose

tests/
  test_production_regressions.py
```

## Documentation

- [Architecture and API Map](ARCHITECTURE_AND_API_MAP.md)
- [Deployment](DEPLOYMENT.md)
- [Security Policy](SECURITY.md)
- [Feature Roadmap](docs/FEATURE_ROADMAP.md)
- [Known Issues](docs/KNOWN_ISSUES.md)
