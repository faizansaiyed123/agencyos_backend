# AgencyOS Recovery Guide

Last verified: 2026-10-20

## Resume procedure

1. Read `PROJECT_STATUS.md`, `IMPLEMENTATION_CHECKLIST.md`, `KNOWN_ISSUES.md`, and `FEATURE_ROADMAP.md`.
2. Read both repository `main` heads and inspect the latest commits.
3. Re-check that source changes described in status docs still exist.
4. Inspect GitHub Actions state before claiming any test result.
5. Continue with the highest-priority unchecked item.

## Current checkpoint

Frontend HEAD: `ee393752d7e8b26c0e0ff660dc44f922caeb6351`
Backend HEAD: `a2dcbe62d8a56ba9c406ec66ad2a37d25351aea9`

Latest backend work:
- runtime dependencies declared;
- refresh-token rotation locked;
- proposal acceptance made atomic;
- idempotent invite/payment transactions serialized;
- regression tests added;
- CI workflow added.

## Safe continuation rules

- Do not reset or force-push.
- Do not overwrite unrelated user changes.
- Re-fetch file SHA before each update.
- Prefer one coherent change per commit.
- After a transaction or auth change, add a regression test.
- Do not mark work verified until a real test/build runner has executed it.

## If network access remains unavailable

Use the GitHub connector for source inspection and writes. Do not claim local execution. Keep documentation current and leave exact next actions.
