# AgencyOS Architecture and API Map

Last verified: 2026-10-20

## Frontend
React 18 + TypeScript + Vite 6, React Router 7.18.4, TanStack Query, Playwright, Nginx production proxy.

## Backend
Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL/Alembic, RLS, MFA, rotating refresh tokens, jobs/outbox, SSE, webhooks, reporting, client portal and billing PDF/email.

## Frontend routes

/login, /signup, /forgot-password, /reset-password, /accept-invite, /portal, /clients, /deals, /proposals, /projects, /work, /invoices, /reports, /team, /settings, /security.

## Backend API

All application routes are under /api/v1.

- Identity: /auth/*, /users, /invites*
- Client portal: /portal/overview, /portal/projects, /portal/proposals*, /portal/invoices*
- CRM: /clients*, /contacts*, /deals*
- Proposals: /proposals*, /proposal-items*
- Projects: /projects*, /tasks*, /milestones*
- Time: /timer/*, /time/*
- Billing: /invoices* including PDF download and queued email
- Collaboration: /comments*, /approvals*, /notifications*
- Files: /files*
- Reporting: /reports/*
- Search: /search, /assistant/ask
- Privacy: /privacy/*
- Flags: /flags*
- Webhooks: /webhooks*
- Ops: /healthz, /readyz

## Security model

Access tokens are short-lived and held in memory. Refresh tokens use httpOnly cookies. Server permissions are authoritative. PostgreSQL RLS supplies tenant isolation. Mutating business workflows use transaction boundaries, and idempotent endpoints serialize concurrent keys.

Client portal queries constrain both org and client account.

## Production topology

Frontend Nginx serves the SPA and proxies /api/* to the backend. The backend and worker run separately from PostgreSQL. SMTP is required in production for invites, password recovery, and invoice delivery.
