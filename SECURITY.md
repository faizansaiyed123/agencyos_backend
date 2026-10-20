# Security Policy

## Supported security boundaries

AgencyOS uses multiple layers:

1. Server-side authorization and tenant checks.
2. PostgreSQL Row-Level Security for tenant-scoped data.
3. Short-lived access tokens and rotating httpOnly refresh tokens.
4. MFA with encrypted TOTP secrets and single-use recovery codes.
5. Password hashing with Argon2id.
6. Rate limiting on authentication and recovery flows.
7. Idempotency protection for sensitive mutating endpoints.
8. Signed outgoing webhooks with private-network checks and retry handling.
9. File type, size, path, and content validation.
10. Security headers at the API and frontend proxy edges.

## Production requirements

Before exposing the service publicly:

- use strong non-development JWT and MFA encryption secrets;
- use HTTPS and secure cookies;
- configure explicit HTTPS CORS origins;
- configure SMTP with a verified sender;
- keep the runtime database role separate from the schema owner;
- use persistent file storage;
- store secrets in the deployment platform's secret manager;
- monitor dead-letter jobs and webhook failures;
- protect PostgreSQL and Redis/external services if introduced later;
- run migrations with the schema-owner connection only.

## Reporting

Do not publish credentials, refresh tokens, reset links, or private tenant data in issues or pull requests. For a suspected vulnerability, provide the smallest reproducible description possible and avoid exploiting real customer data.
