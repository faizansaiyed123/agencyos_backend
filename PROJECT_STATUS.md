# AgencyOS Project Status

Last verified: 2026-10-20

## Access

GitHub access is verified for both repositories with admin/maintain/push permissions on `main`.

Current heads:
- Frontend: `ee393752d7e8b26c0e0ff660dc44f922caeb6351`
- Backend: `a2dcbe62d8a56ba9c406ec66ad2a37d25351aea9`

Local repository execution is not available in this session because the container cannot resolve github.com. GitHub source inspection and writes are available.

## Verified architecture

Frontend:
- React 18 + TypeScript + Vite
- React Router
- TanStack Query
- In-memory access token + httpOnly refresh cookie
- Real backend API calls; no mock response layer found

Backend:
- Python 3.12
- FastAPI
- SQLAlchemy 2
- PostgreSQL + Alembic
- Argon2id passwords
- JWT access tokens and rotating refresh tokens
- PostgreSQL RLS tenant isolation
- Worker/job queue
- SSE notifications
- Signed/retried webhooks
- Feature flags, privacy export/erasure, tracing

## Completed in this audit session

- Verified repository permissions and branch state.
- Audited repository trees and key auth/API/business modules.
- Added missing runtime dependencies for httpx, multipart uploads, and OpenTelemetry.
- Fixed refresh-token rotation concurrency by locking the refresh row during rotation.
- Fixed proposal acceptance transaction boundaries so proposal + project + deal changes commit together.
- Added regression tests for those areas and related production checks.
- Added backend and frontend GitHub Actions workflows.
- Fixed idempotency concurrency for invite/payment requests with a transaction-level advisory lock and same-transaction business/result commit.
- Added persistent project tracking documents.

## Not yet verified

No local test suite has been executed because repository cloning is blocked by the environment's network/DNS. GitHub Actions workflow runs were created, but GitHub currently reports zero jobs for the backend runs and no frontend run has appeared, so CI is not evidence of a pass yet.

## Significant incomplete/product gaps

- Password-recovery workflow is referenced in the frontend README but no password-recovery UI/API was found.
- Client role currently has no permissions and therefore has no functional client portal.
- Production email delivery is not implemented; the current email abstraction is console/memory.
- Invoice PDF rendering/emailing and payment reversal/credit-note flows are not implemented.
- File storage is local disk only; an object-storage adapter is not implemented.
- Frontend has no automated browser/unit test command despite Playwright being installed.
- Frontend request handling lacks a general timeout/offline/retry layer for safe transient GETs.
- CI runner execution still needs to be resolved and then rerun.
