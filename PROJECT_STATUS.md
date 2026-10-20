# AgencyOS Project Status

Last verified: 2026-10-20

## Access

GitHub access is verified for both repositories with admin/maintain/push permissions on `main`.

Current heads:
- Frontend: `9cc8899f8e2eee9bbed745a4802a24b446ba9349`
- Backend: current head is the latest commit on `main`; this file is refreshed at the end of each checkpoint.

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

No local test suite has been executed in this session. Frontend GitHub Actions is executing build, Playwright smoke tests, and Docker build. Backend workflow runs continue to conclude as failures without job records exposed by the connected GitHub API.

## Significant remaining production work

- Backend GitHub Actions still reports failed workflow runs with no job records exposed through the connected Actions API; source-level verification continues through targeted regression coverage.
- Production still requires deployment-specific SMTP credentials, verified sender, real database credentials, and persistent file storage.
- Payment reversal/credit-note accounting remains intentionally outside the current billing model.
- Final production smoke test must be run after infrastructure credentials are supplied.
- File storage is local disk only; an object-storage adapter is not implemented.
- Frontend has no automated browser/unit test command despite Playwright being installed.
- Backend CI runner/job observability still needs to be resolved; frontend CI is executing normally.
