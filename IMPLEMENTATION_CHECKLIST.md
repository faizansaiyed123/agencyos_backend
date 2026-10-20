# AgencyOS Implementation Checklist

Legend: ✅ complete for the current deployable release; 🔧 deploy-time configuration; 📌 future enhancement.

## Release verification

- ✅ Frontend production build
- ✅ Frontend Playwright browser smoke test
- ✅ Frontend Docker build
- ✅ Backend Ruff
- ✅ Backend regression tests
- ✅ Backend Docker build
- ✅ Cross-repository backend compatibility
- ✅ npm security audit with patched React Router 7.18.4

## Backend

- ✅ FastAPI health/readiness
- ✅ RLS tenant isolation
- ✅ Authentication/MFA/password recovery
- ✅ Refresh-token rotation and concurrency protection
- ✅ Rate limiting
- ✅ Transactional jobs/outbox
- ✅ Idempotency and transaction safety
- ✅ Audit logging
- ✅ Notifications/SSE
- ✅ Signed webhooks
- ✅ Feature flags/privacy controls/tracing
- ✅ CRM/proposals/projects/time
- ✅ Billing/payments/invoice PDF/email
- ✅ Files/reporting/search
- ✅ Client portal
- ✅ Security headers and production configuration validation
- ✅ Non-root Docker image

## Frontend

- ✅ Authentication/MFA/password recovery
- ✅ CRM/pipeline/proposals/projects/work/invoices/reports/team/settings/security
- ✅ Client portal
- ✅ Responsive layout and mobile navigation
- ✅ Request timeout/retry/offline UX
- ✅ Playwright browser smoke tests
- ✅ Production Docker/Nginx image
- ✅ CSP/security headers
- ✅ React Router 7.18.4

## Deployment

- ✅ Dockerfiles
- ✅ Docker Compose development stack
- ✅ Same-origin Nginx API proxy
- ✅ Deployment documentation
- 🔧 PostgreSQL/SMTP/domain/secrets/persistent storage values

## Future enhancements

- 📌 Refunds/credit notes
- 📌 Object-storage adapter
- 📌 Expanded E2E coverage
- 📌 Advanced saved filters/bulk actions
