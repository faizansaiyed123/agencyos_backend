# AgencyOS Feature Roadmap

Last verified: 2026-10-20

## P0 — production blockers

| Feature / problem | Benefit | Backend | Frontend | Status |
|---|---|---|---|---|
| CI runner verification | Prevent unverified releases | workflow/debugging | n/a | in progress |
| Password recovery | Account recovery | reset-token/email endpoints | recovery pages | planned |
| Production email provider | Real invites/transactional mail | provider adapter/job | status UX | planned |
| Client portal | Lets clients participate directly | client permissions/endpoints | dedicated portal | planned |

## P1 — reliability and UX

| Feature | Benefit | Status |
|---|---|---|
| Safe GET timeout/retry + offline state | Better network resilience | planned |
| Browser regression suite | Protect critical workflows | planned |
| Object storage adapter | Production file durability | planned |
| Deployment headers/CSP | Browser hardening | planned |

## P2 — billing and collaboration maturity

| Feature | Benefit | Status |
|---|---|---|
| Invoice PDF | Professional invoicing | planned |
| Invoice email delivery | Faster collections | planned |
| Refund/credit-note model | Correct financial reversals | planned |
| Client approval portal | Faster proposal/project approvals | planned |
| Advanced saved filters/bulk actions | Better agency operations | planned |

## Completed production-oriented capabilities

- Multi-tenant RLS
- MFA
- Rotating refresh tokens
- Rate limiting
- Idempotency primitives
- Audit logs
- Job queue
- SSE notifications
- Signed outgoing webhooks with retries
- Feature flags
- Privacy export/erasure
- OpenTelemetry tracing
- Projects/time/billing/collaboration/files/reporting modules
