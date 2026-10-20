# AgencyOS Known Issues

Last verified: 2026-10-20

## Critical / blocking

### CI runner execution unavailable
GitHub Actions workflow runs have been created, but the GitHub API currently reports zero jobs for backend runs and no frontend run result. Therefore CI cannot yet be used as test evidence.

Next action: verify repository Actions availability/settings and rerun after the workflow is recognized by a runner.

### No local repository execution
The container cannot resolve github.com, so clone/install/test commands cannot be performed locally in this session.

Next action: use GitHub Actions or a network-enabled execution environment.

## High priority

### Production email delivery
Password recovery and invite emails are now queued, but the configured production email backend is still console-based; a real provider is required before external users can receive mail.

### Client role has no product workflow
The role exists but the permission matrix is empty. This means a client account does not currently have a usable portal.


### Idempotency and refresh concurrency
Fixed in this audit. Regression tests were added, but execution still needs a real test environment.

## Medium priority

### Local file storage
Current storage is filesystem-backed. Production needs a persistent volume or object storage adapter.

### Billing completeness
Refunds/credits and invoice PDF/email are not implemented.

### Frontend resilience
The fetch layer handles a single auth refresh but does not yet provide general safe-request timeout, transient retry, and explicit offline/reconnect state.

### Frontend automated testing
Playwright is installed but there is no test script/configured CI job for browser tests.

## Low priority / hardening

- Add stronger JWT issuer/audience validation if deployment topology warrants it.
- Add explicit CSP/security headers at the deployment edge.
- Consider DNS-rebinding-safe outbound webhook transport if webhook destinations become high-risk.
