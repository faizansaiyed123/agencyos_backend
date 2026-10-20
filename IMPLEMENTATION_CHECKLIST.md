# AgencyOS Implementation Checklist

Legend: ✅ verified in source; ⚠️ implemented but execution not yet verified; ⬜ incomplete/not implemented.

## Repository and recovery
- ✅ Repository access verified for both repositories.
- ✅ Main branch state verified.
- ✅ Persistent project tracking files started.
- ⚠️ CI workflows added; runner results unavailable.
- ⬜ Clean-environment build/test verification.

## Backend foundations
- ✅ FastAPI app and health/readiness routes.
- ✅ Structured problem+json errors.
- ✅ PostgreSQL RLS tenant isolation architecture.
- ✅ Access/refresh authentication with MFA.
- ✅ Password hashing and login lockout.
- ✅ Idempotency infrastructure.
- ✅ Rate limiting.
- ✅ Job queue and worker.
- ✅ Audit logging.
- ✅ SSE notifications.
- ✅ Signed webhooks with retry queue.
- ✅ Feature flags.
- ✅ Privacy export/erasure.
- ✅ OpenTelemetry integration.
- ✅ Runtime dependency declaration corrected.
- ✅ Refresh-token concurrency fixed in source.
- ✅ Idempotency concurrency fixed in source.
- ✅ SMTP email sender and production configuration validation.

## Business modules
- ✅ CRM clients/contacts/deals.
- ✅ Proposal lifecycle.
- ✅ Projects/tasks/milestones/team.
- ✅ Time tracking.
- ✅ Billing/invoices/payments.
- ✅ Collaboration/comments/approvals/notifications.
- ✅ Files.
- ✅ Reporting/search.
- ✅ Proposal acceptance now uses one transaction for proposal/project/deal changes.
- ⬜ Payment refunds/credits.
- ⬜ Invoice PDF and outbound invoice email.
- ⬜ Object-storage production adapter.

## Frontend
- ✅ Auth/MFA/invite acceptance UI.
- ✅ Clients, pipeline, proposals, projects, work, invoices, reports, team, settings, security.
- ✅ Real API hooks and role-aware navigation.
- ⚠️ Responsive/polish audit still required across every screen.
- ✅ Password reset UI/API.
- ⬜ Functional client portal.
- ⬜ Browser/unit test suite.
- ✅ Generic safe GET timeout/retry/offline UX.

## Documentation/deployment
- ✅ Project master/status/checklist.
- ✅ Architecture/API map.
- ✅ Known issues and recovery docs.
- ✅ Feature roadmap.
- ⚠️ CI definitions added.
- ⬜ CI green with actual runner output.
- ⬜ Docker/production deployment verification.
- ⬜ Clean-environment setup verification.

## Final verification
- ⬜ Backend tests actually executed.
- ⬜ Frontend production build actually executed.
- ⬜ End-to-end browser workflow verification.
- ⬜ Deployment verified.
