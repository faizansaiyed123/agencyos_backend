# AgencyOS Architecture and API Map

Last verified: 2026-10-20

## Repositories

### Frontend
React/TypeScript/Vite application.
- Entry: `src/main.tsx`
- Routing: `src/App.tsx`
- Auth state: `src/auth/AuthContext.tsx`
- API transport: `src/api/client.ts`
- API hooks/types: `src/api/hooks.ts`, `src/api/types.ts`
- Shared UI: `src/components/*`
- Pages: `src/pages/*`

### Backend
FastAPI application.
- Entry: `app/main.py`
- Core auth/security/db/config/errors: `app/core/*`
- Business modules: `app/modules/*`
- Platform services: `app/platform/*`
- Worker: `app/worker.py`
- Migrations: `migrations/versions/*`

## Frontend routes

`/`, `/login`, `/signup`, `/accept-invite`, `/clients`, `/clients/:id`, `/deals`, `/deals/:id`, `/proposals`, `/proposals/:id`, `/projects`, `/projects/:id`, `/work`, `/invoices`, `/invoices/:id`, `/reports`, `/team`, `/settings`, `/security`.

## Backend API groups

All application routes are under `/api/v1`.

- Identity: `/auth/*`, `/users`, `/invites*`
- CRM: `/clients*`, `/contacts*`, `/deals*`
- Proposals: `/proposals*`, `/proposal-items*`
- Projects: `/projects*`, `/tasks*`, `/milestones*`
- Time: `/timer/*`, `/time/*`
- Billing: `/invoices*`
- Collaboration: `/comments*`, `/approvals*`, `/notifications*`
- Files: `/files*`
- Reporting: `/reports/*`
- Search: `/search`, `/assistant/ask`
- Privacy: `/privacy/*`
- Feature flags: `/flags*`
- Webhooks: `/webhooks*`
- Ops: `/healthz`, `/readyz`

## Core security flow

1. Browser receives short-lived access token in memory.
2. Refresh token is kept in an httpOnly cookie.
3. API validates bearer token and resolves the user/org from the database.
4. Server-side permissions are enforced by dependencies.
5. PostgreSQL RLS enforces tenant isolation.
6. Mutating workflows use transactions; idempotent endpoints use a transaction-level lock and persist the cached response with the business change.

## Key cross-module transaction

Proposal acceptance:
proposal -> project creation -> deal value sync -> deal stage transitions -> single commit.

## Integration contract

The frontend uses `/api/v1` from the same origin and relies on the backend's problem+json error contract. Production should place frontend and API behind a shared origin/reverse proxy or otherwise configure CORS and secure cookies consistently.
