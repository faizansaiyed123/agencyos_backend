# AgencyOS Project Status

Last verified: 2026-10-20

## Access

GitHub access is verified for both repositories with admin/maintain/push permissions on `main`.

Current heads:
- Frontend: `60c3eb1ce1622d1be1a6fd31569f69e7a1e57810`
- Backend: `891b06fedd9361892bfe607247926e0da8d7a978`

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

No local test suite has been executed because repository cloning is blocked by the environment's network/DNS. Frontend GitHub Actions has successfully executed the production build. Backend workflow runs are currently concluding as failures; the connected GitHub job/log APIs are not exposing the individual job details, so the exact failing step still needs to be recovered.

## Significant incomplete/product gaps

- Client role currently has no permissions and therefore has no functional client portal.
- Production email delivery still requires deployment-specific SMTP credentials and provider configuration, but the SMTP sender is implemented.
- Invoice PDF rendering/emailing and payment reversal/credit-note flows are not implemented.
- File storage is local disk only; an object-storage adapter is not implemented.
- Frontend has no automated browser/unit test command despite Playwright being installed.
- CI runner execution still needs to be resolved and then rerun.
