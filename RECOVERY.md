# AgencyOS Recovery Guide

Last verified: 2026-10-20

## Verified release heads

Frontend: 9a330d1c06a04e9b7d80bd0f1e142a65d184a2df
Backend: 47c0179c91a54ab86d7810785e186bd9c050f813

## Release gate

The frontend repository CI verifies npm install, production build, Playwright browser smoke tests, and Docker build.
The frontend repository Backend compatibility workflow verifies the current backend main with dependency installation, Ruff, pytest, and Docker build.

The verified release gates are green.

## Continue safely

- Keep main deployable.
- Re-fetch file SHAs before edits.
- Add regression tests for security or transaction changes.
- Re-run the backend compatibility workflow after backend code changes.
- Treat roadmap enhancements as post-release work.

## Production setup

After deployment values are supplied:
- run `alembic upgrade head`;
- configure the API runtime as the non-owner database role;
- configure the standalone worker;
- verify `/healthz` and `/readyz`;
- smoke-test login, MFA, password recovery, client portal, invoice PDF/email, and logout.
