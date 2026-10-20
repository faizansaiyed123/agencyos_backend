# AgencyOS Recovery Guide

Last verified: 2026-10-20

## Resume procedure

1. Read `PROJECT_STATUS.md`, `IMPLEMENTATION_CHECKLIST.md`, `KNOWN_ISSUES.md`, and `FEATURE_ROADMAP.md`.
2. Read both repository `main` heads and inspect the latest commits.
3. Re-check that source changes described in status docs still exist.
4. Inspect GitHub Actions state before claiming any test result.
5. Continue with the highest-priority unchecked item.

## Current checkpoint

Frontend HEAD: `9cc8899f8e2eee9bbed745a4802a24b446ba9349`
Backend HEAD: `8c7db4e01b412d9b4107f5ff36dc8159829a03b5`

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
