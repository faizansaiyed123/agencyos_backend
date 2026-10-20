# AgencyOS Project Master Plan

Status: active development
Last verified: 2026-10-20

## Mission

AgencyOS is a full-stack digital-agency operations platform split across two repositories:

- Frontend: `faizansaiyed123/agencyos_frontend`
- Backend: `faizansaiyed123/agencyos_backend`

The goal is a production-oriented application with real frontend/backend integration, tenant isolation, secure authentication, reliable business workflows, polished UX, automated verification, and deployment-ready documentation.

## Working rules

1. Never report a change, test, commit, or deployment as complete unless it was actually verified.
2. Preserve existing working behavior and prefer targeted changes over rewrites.
3. Keep backend authorization authoritative; frontend permission checks are presentation-only.
4. Treat PostgreSQL RLS as a second tenant-isolation boundary.
5. Use transactions for business invariants and idempotency-sensitive operations.
6. Keep project state in repository documentation so interrupted sessions can resume without relying on chat memory.

## Definition of done

Both repositories must have their actual source audited, intended workflows implemented, critical security and reliability problems addressed, frontend/backend contracts aligned, builds/tests executed where infrastructure permits, deployment configuration documented, and remaining blockers explicitly recorded.

## Current scope

Existing modules include identity/MFA, CRM, proposals, projects, time tracking, billing, collaboration, files, reporting, search/assistant, privacy, feature flags, notifications/SSE, webhooks, tracing, job queue, rate limiting, audit logging, and idempotency.

Near-term priorities are:
1. finish production reliability/security audit;
2. make CI reproducible and obtain real runner results;
3. close frontend/backend contract gaps;
4. implement remaining high-value incomplete workflows;
5. polish UX/responsiveness/accessibility;
6. document and verify deployment.

## Repository policy

Changes are currently being made directly to `main` because the repositories contain only the initial branch and the connected GitHub access has admin/push permission. Destructive history operations are not used.
