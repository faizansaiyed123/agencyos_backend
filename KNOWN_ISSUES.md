# AgencyOS Known Issues

Last verified: 2026-10-20

## Release blockers

None found in the verified release pipeline.

## Deploy-time configuration

Production requires real PostgreSQL credentials, strong JWT/MFA secrets, HTTPS/CORS configuration, SMTP credentials and verified sender, persistent file storage, and domain/TLS/reverse-proxy configuration.

## Future enhancements

- Payment refunds / credit notes
- Object-storage adapter
- Expanded browser scenario coverage
- Advanced saved filters / bulk actions

These are post-release enhancements, not blockers to the current deployable build.

## Security posture

RLS tenant isolation, MFA, Argon2id passwords, rotating refresh-token locks, rate limits, idempotency locks, signed webhooks, file validation, CSP/security headers, and client-portal scoping are implemented.
