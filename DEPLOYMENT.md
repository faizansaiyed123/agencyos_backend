# AgencyOS Backend Deployment

## Deployable release

The current release has passed the backend Ruff/tests/Docker gate and the frontend build/browser/Docker/security gates.

## Production architecture

- Browser: https://app.example.com
- Frontend: Nginx SPA with /api/* reverse proxy
- Backend: FastAPI/Uvicorn
- Worker: python -m app.worker
- PostgreSQL: managed or persistent PostgreSQL
- File storage: persistent volume for the shipped filesystem provider
- SMTP: required for transactional email

Same-origin deployment is recommended because the refresh token uses a secure httpOnly cookie.

## Production environment

Set:
- AGENCYOS_ENV=prod
- strong AGENCYOS_JWT_SECRET
- strong AGENCYOS_MFA_ENCRYPTION_KEY
- AGENCYOS_DATABASE_URL
- AGENCYOS_MIGRATION_DATABASE_URL
- HTTPS AGENCYOS_CORS_ORIGINS
- AGENCYOS_COOKIE_SECURE=true
- AGENCYOS_APP_BASE_URL=https://app.example.com
- AGENCYOS_EMAIL_BACKEND=smtp
- SMTP host/port/credentials/from address
- persistent AGENCYOS_STORAGE_DIR
- tracing settings where required

The app rejects unsafe production configuration.

## Database

Run migrations with the schema-owner connection:

alembic upgrade head

Run the application with the non-owner runtime role.

## Worker

Run:

python -m app.worker

The worker handles email, webhooks, proposal jobs and other durable work.

## Billing and client portal

- Issued invoices can be rendered as PDFs.
- Invoice emails are queued through the worker.
- Client users are created through client-linked invites and receive a scoped portal.
- Client proposal decisions and invoice access are tenant/client constrained.

## Docker

Backend:

docker build -t agencyos-backend .

Development stack:

docker compose up --build

## Health

- /healthz — liveness
- /readyz — readiness

## Secrets

Never commit production secrets. Put them in the deployment platform's secret manager.
