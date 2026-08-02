# Wave 5 / SAATHI-295 — Independent QA Final Report Template

> Template only. Initial classification: **NOT EXECUTED**. Do not change the
> classification without raw exact-commit evidence.

## 1. Provenance and access matrix

- Required commit: `<hash>`
- Tested commit: `<hash>`
- Branch/PR: `<branch>` / `<real URL or NONE>`
- Remote equality: `<PASS/FAIL/BLOCKED + evidence>`
- Worktree status: `<clean/dirty + evidence>`
- Host/runtime: `<OS, architecture, Python, Node, PostgreSQL, Chromium>`
- CI: `<complete real job table with URLs, or BLOCKED>`

| Capability | Available | Version/evidence | Consequence |
|---|---|---|---|
| Repository/exact commit | NOT EXECUTED | | |
| PostgreSQL | NOT EXECUTED | | |
| Chromium/Playwright | NOT EXECUTED | | |
| GitHub remote/CI | NOT EXECUTED | | |
| Jira read/comment/transition | NOT EXECUTED | | |

## 2. Changed-file and contract audit

- Base..head files: `<count and artifact>`
- Out-of-scope files: `<zero or list>`
- Migration predecessor/head: `<observed>`
- S-90–S-93 mapping/parity: `<observed>`
- ICS-only/no-OAuth assertion: `<observed>`

## 3. Gate results

| Gate | Expected | Actual | Result | Raw evidence |
|---|---|---|---|---|
| Backend native suite | 0 failed | NOT EXECUTED | NOT EXECUTED | |
| Frontend typecheck/lint/build/tests | RC 0 / 0 failed | NOT EXECUTED | NOT EXECUTED | |
| Alembic up/check/down/up | RC 0 | NOT EXECUTED | NOT EXECUTED | |
| Required calendar tables/constraints | Complete contract | NOT EXECUTED | NOT EXECUTED | |
| HTTP event/preferences/conflict/export | Complete contract | NOT EXECUTED | NOT EXECUTED | |
| PostgreSQL concurrency/rollback | Complete contract | NOT EXECUTED | NOT EXECUTED | |
| RFC 5545 independent parser | Valid/feed-private | NOT EXECUTED | NOT EXECUTED | |
| Playwright S-90–S-93 | Complete journeys | NOT EXECUTED | NOT EXECUTED | |
| Geometry/axe/keyboard | Complete matrix | NOT EXECUTED | NOT EXECUTED | |
| Privacy canary scan | 0 residual findings | NOT EXECUTED | NOT EXECUTED | |
| Registration/Waves 1–4 regression | 0 failed | NOT EXECUTED | NOT EXECUTED | |

## 4. Negative Test Results

Copy every N-01–N-55 row from
`docs/product/wave5_calendar_interop/NEGATIVE_TEST_MATRIX.md` and complete this
table. Omitting a row makes final classification NOT EXECUTED.

| ID | Exact input | Expected failure/outcome | Actual HTTP/UI/DB outcome | Before/after mutations | Result | Evidence |
|---|---|---|---|---|---|---|
| N-01 | `<input>` | 422/no mutation | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED | |

## 5. Database and data-location confirmation

| Domain data | Table(s) observed | Sensitive fields/control | Row/constraint evidence |
|---|---|---|---|
| Events/sources | `calendar_events`, `calendar_event_sources` | user scoped; restricted projection | NOT EXECUTED |
| Conflicts | `calendar_conflicts` | user scoped; deterministic source refs | NOT EXECUTED |
| Reminder preferences | `calendar_reminder_preferences` | user scoped/version safe | NOT EXECUTED |
| Export subscription | `calendar_export_subscriptions` | status/expiry, no raw capability | NOT EXECUTED |
| Export token metadata | `calendar_export_tokens`, `calendar_export_revocations` | keyed hash only | NOT EXECUTED |
| Audit | `audit_events` | redacted snapshots | NOT EXECUTED |

## 6. Privacy and threat-model results

- Raw capability storage scan: `NOT EXECUTED`
- Public-route log/audit/error redaction: `NOT EXECUTED`
- Feed allowlist and forbidden canaries: `NOT EXECUTED`
- Browser storage/console/network scan: `NOT EXECUTED`
- Scanner seeded-canary self-test: `NOT EXECUTED`

## 7. Jira lifecycle read-back

| Ticket | Starting status | Final status | Transition/comment evidence |
|---|---|---|---|
| SAATHI-285 | `<live>` | `<live>` | |
| SAATHI-286 | `<live>` | `<live>` | |
| SAATHI-287 | `<live>` | `<live>` | |
| SAATHI-288 | `<live>` | `<live>` | |
| SAATHI-289 | `<live>` | `<live>` | |
| SAATHI-290 | `<live>` | `<live>` | |
| SAATHI-291 | `<live>` | `<live>` | |
| SAATHI-292 | `<live>` | `<live>` | |
| SAATHI-293 | `<live>` | `<live>` | |
| SAATHI-294 | `<live>` | `<live>` | |
| SAATHI-295 | `<live>` | `<live>` | |
| SAATHI-296 | `<live>` | `<live>` | |
| SAATHI-297 | `<live>` | `<live>` | |
| SAATHI-298 | `<live>` | `<live>` | |
| SAATHI-299 | `<live>` | `<live>` | |

## 8. Findings, drift and blockers

| ID | Severity | Reproduction | Root cause | Owner | Status/evidence |
|---|---|---|---|---|---|
| `<id>` | `<severity>` | `<steps>` | `<cause>` | `<ticket>` | `<open/fixed/blocked>` |

Explicitly distinguish an implementable defect from an unavailable external
runtime. Never infer closure from Engineering prose or an earlier hash.

## 9. Final classification

`NOT EXECUTED | PASS | FAIL | BLOCKED | PARTIAL`

Reason: `<evidence-backed explanation>`

Remaining work: `<complete list>`

## 10. Evidence integrity

- SHA-256 entries: `<count>`
- `sha256sum -c` / `shasum -a 256 -c`: `<actual result>`
- Raw token/path sanitizer: `<actual result>`
- Report author/role: `<truthful role; do not impersonate a person>`
