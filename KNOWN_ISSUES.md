# AgencyOS Known Issues

Last verified: 2026-10-20

## Critical / blocking

### CI runner execution unavailable
Frontend CI has passed build, browser smoke tests, and Docker build on recent commits; the latest documentation-only run is still in progress. Backend CI runs currently conclude as failures with zero jobs/logs exposed by the available GitHub connector, so the exact failing step remains unobservable.

Next action: verify repository Actions availability/settings and rerun after the workflow is recognized by a runner.

### No local repository execution
The container cannot resolve github.com, so clone/install/test commands cannot be performed locally in this session.

Next action: use GitHub Actions or a network-enabled execution environment.

## High priority

### Production email delivery
SMTP delivery is implemented and required in prod, but deployment still needs real provider credentials and a verified sender address.

### Client role has no product workflow
The role exists but the permission matrix is empty. This means a client account does not currently have a usable portal.


### Idempotency and refresh concurrency
Fixed in this audit. Regression tests were added, but execution still needs a real test environment.

## Medium priority

### Local file storage
Current storage is filesystem-backed. Production needs a persistent volume or object storage adapter.

### Billing completeness
Refunds/credits and invoice PDF/email are not implemented.


### Frontend automated testing
Playwright is installed but there is no test script/configured CI job for browser tests.

## Low priority / hardening

- Add stronger JWT issuer/audience validation if deployment topology warrants it.
- Add explicit CSP/security headers at the deployment edge.
- Consider DNS-rebinding-safe outbound webhook transport if webhook destinations become high-risk.
