# NYAY-20 CI Remediation Engineering Report

## Verdict

LOCAL REMEDIATION GATES PASS for source commit
`e429d2e06752cb0ba38835fcd709b96a0ad08e7e`.

This is not remote CI success, independent QA, Testing, production readiness or
external-user approval.

## Reproduced failure

NyayOne PR #3 run `32016852185`, job `95348149620`, failed in
`backend-postgres16-gate`. `backend/scripts/db_gate.sh` intentionally removed
`DATABASE_URL` for its unit/HTTP-contract stage but inherited
`APP_ENV=staging`. The resulting staging-plus-local-default combination was
correctly rejected during module import by the new fail-closed database
credential validator.

## Correction

- Only the database gate's unit/HTTP-contract subprocess now runs with the
  explicit test environment while `DATABASE_URL` is absent.
- All subsequent Alembic, schema, PostgreSQL concurrency and Wave 2 stages keep
  the caller's staging environment and target `DATABASE_URL`.
- A source-level regression test pins this subprocess boundary.
- No migration file changed.

## Local exact-source results

- Targeted configuration/runtime-isolation tests: 38 passed.
- Complete backend: 1206 passed, 4 skipped, 0 failed.
- Runtime identity policy passed.
- Five planted policy tests passed.
- Workflow policy passed for 7 workflows.
- Evidence verifier passed 5 manifests / 312 files before this package.
- `git diff --check` passed.

## Pending

- Publish this descendant and verify local HEAD equals remote branch and PR head.
- Required GitHub checks must all pass on the new exact PR head.
- Claude Code must independently rerun the exact remote head.
