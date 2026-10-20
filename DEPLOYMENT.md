# AgencyOS Backend Deployment

## Production architecture

Run the frontend and backend behind the same public origin when possible.

- Browser: https://app.example.com
- Frontend container: Nginx serves the SPA and proxies /api/*
- Backend container: FastAPI/Uvicorn on an internal network
- Worker container: python -m app.worker
- PostgreSQL: managed PostgreSQL or the supplied development container
- File storage: persistent volume for small/self-hosted deployments; object storage adapter remains a future hardening item
- SMTP: required in production for transactional email, including password resets, invites, and invoice PDFs

The frontend API client already targets /api/v1, so same-origin proxying keeps the refresh cookie and API requests on one site.

## Backend environment

At minimum in production configure:

- AGENCYOS_ENV=prod
- strong AGENCYOS_JWT_SECRET
- strong AGENCYOS_MFA_ENCRYPTION_KEY
- AGENCYOS_DATABASE_URL
- AGENCYOS_MIGRATION_DATABASE_URL
- AGENCYOS_CORS_ORIGINS with the actual frontend origin if cross-origin requests are used
- AGENCYOS_COOKIE_SECURE=true
- AGENCYOS_APP_BASE_URL=https://app.example.com
- AGENCYOS_EMAIL_BACKEND=smtp
- SMTP host/port/credentials/from address
- persistent AGENCYOS_STORAGE_DIR or a future object-store adapter
- tracing settings when required

The application rejects production startup when development secrets or non-SMTP email delivery are used.

## Migrations

Run migrations with the schema-owner connection:

alembic upgrade head

The runtime role is deliberately non-owner and RLS-protected. Never run the application as the migration/schema-owner role.

## Billing and client portal

- Issued invoices can be downloaded as PDFs and queued for email delivery.
- Client users receive access through client-linked invites and the scoped client portal.
- The standalone worker must register and process the billing email job; the shipped worker does this automatically.

## Worker

Run one or more worker processes with:

python -m app.worker

The worker handles queued email, webhook deliveries, proposal jobs, and other durable background work.

## Docker

Build and run the backend image:

docker build -t agencyos-backend .

Run the supplied development backend stack:

docker compose up --build

This starts PostgreSQL, runs Alembic migrations, starts the API, and starts the worker.

## Health endpoints

- /healthz — process/liveness check
- /readyz — database readiness check

The deployment platform should use /healthz for liveness and /readyz for readiness.

## Secrets

Do not commit production .env files. Store production credentials in the deployment platform's secret manager. Rotate any credential that has ever been exposed in logs, commits, or screenshots.
