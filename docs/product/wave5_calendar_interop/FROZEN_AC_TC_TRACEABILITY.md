# Wave 5 — Frozen Acceptance/Test Traceability Matrix

Frozen: 2026-08-02

Exact base: `adf191dfa6d3229e58e5df0cd8d35f87ad4fb8ae`

Status of every row at freeze time: **NOT EXECUTED**

The matrix is intentionally end-to-end. A frontend unit test is not a
substitute for an authenticated HTTP/PostgreSQL proof, SQLite is not a
substitute for PostgreSQL concurrency, and a generated `.ics` string is not a
substitute for a real subscriber fetch through the public capability route.

## Jira ownership

| Ticket | Owner contract |
|---|---|
| SAATHI-285 | Parent: aggregate cross-module events and personal-event persistence |
| SAATHI-286 | S-90/S-91 frontend integration and responsive/accessibility states |
| SAATHI-287 | Event normalization, source adapters, dedupe, timezone and restricted projection |
| SAATHI-288 | S-90/S-91 API, PostgreSQL, browser, negative and privacy QA |
| SAATHI-289 | S-90/S-91 UX/reference/state parity |
| SAATHI-290 | Parent: reminder-preference persistence and delivery contract |
| SAATHI-291 | S-93 reminder-preference frontend integration |
| SAATHI-292 | Reminder-preference service/API/database contract |
| SAATHI-293 | S-93 API, PostgreSQL, browser, negative and privacy QA |
| SAATHI-294 | S-93 UX/reference/state parity |
| SAATHI-295 | Parent: conflict detection and external iCalendar export |
| SAATHI-296 | S-92/S-93 conflict/export frontend integration |
| SAATHI-297 | Conflict/export service, public feed, token security and PostgreSQL schema |
| SAATHI-298 | Conflict/export API, PostgreSQL, browser, negative, privacy and concurrency QA |
| SAATHI-299 | S-92/S-93 UX/reference/state parity |

## Canonical Jira test-case ownership

| Canonical test case | Binding acceptance | Primary implementation / QA / UX owners | Required evidence |
|---|---|---|---|
| TC-285-01 | Aggregate at least two source adapters and sort chronologically | 287 / 288 / 289 | `api/events.json`, `playwright/s90/` |
| TC-285-02 | Source/date filters persist across refresh | 286, 287 / 288 / 289 | `playwright/s90/filters/` |
| TC-285-03 | Stable source tuple dedupes repeats without dropping distinct events | 287 / 288 | `api/events_dedupe.json` |
| TC-285-04 | Selected timezone and date-boundary projection is deterministic | 286, 287 / 288 / 289 | `postgres/timezone_matrix.json`, `playwright/s90/timezone/` |
| TC-285-05 | Loading, empty and partial-source failure keep healthy results and retry only failed sources | 286, 287 / 288 / 289 | `playwright/s90/state_matrix.json` |
| TC-285-06 | Valid deep link works; missing/unauthorised source is handled safely | 286, 287 / 288 / 289 | `api/deep_link_auth.json`, `playwright/s90/deep_links/` |
| TC-285-07 | Restricted notes, evidence URLs and private identifiers never appear in previews | 287 / 288 | `privacy/event_projection_scan.json` |
| TC-285-08 | S-90/S-91 responsive/theme/accessibility/console/network matrix | 286 / 288 / 289 | `playwright/s90/`, `playwright/s91/`, `screenshots/` |
| TC-290-01 | New-user defaults and returning-user preferences load from the server | 291, 292 / 293 / 294 | `api/reminder_preferences.log`, `playwright/s93/preferences/` |
| TC-290-02 | Supported reminder types enable/disable and survive refresh | 291, 292 / 293 / 294 | `playwright/s93/preferences/persistence.json` |
| TC-290-03 | Lead-time, quiet-hour and IANA-timezone boundaries reject invalid input typed and closed | 292 / 293 | `api/reminder_boundaries.json` |
| TC-290-04 | Repeated idempotent save creates no duplicate preference/audit row | 292 / 293 | `postgres/reminder_idempotency.json` |
| TC-290-05 | Opt-out suppresses preview/scheduling eligibility | 291, 292 / 293 / 294 | `api/reminder_optout.json`, `playwright/s93/preferences/optout/` |
| TC-290-06 | Preview contains no sensitive event detail or private identifier | 291, 292 / 293 / 294 | `privacy/reminder_preview_scan.json` |
| TC-290-07 | Cross-user read/write is rejected without enumeration | 292 / 293 | `api/authorization_matrix.json` |
| TC-290-08 | S-93 responsive/theme/accessibility/console/network matrix | 291 / 293 / 294 | `playwright/s93/preferences/`, `screenshots/` |
| TC-295-01 | Detect full, partial and contained interval overlaps | 297 / 298 / 299 | `api/conflict_matrix.json`, `playwright/s92/` |
| TC-295-02 | Adjacent half-open intervals are not conflicts | 297 / 298 | `api/conflict_matrix.json` |
| TC-295-03 | Timezone conversion and DST boundaries are deterministic | 297 / 298 | `postgres/timezone_matrix.json` |
| TC-295-04 | A conflict pair appears once, never reversed/duplicated | 297 / 298 | `api/conflict_matrix.json` |
| TC-295-05 | Export capability returns only privacy-eligible ICS fields | 296, 297 / 298 / 299 | `ics/feed_contract.log`, `ics/privacy_allowlist.json` |
| TC-295-06 | Revocation immediately disables subsequent feed requests; repeat revoke is idempotent | 296, 297 / 298 / 299 | `api/export_lifecycle.log` |
| TC-295-07 | Another user cannot read, rotate or revoke an export | 297 / 298 | `api/authorization_matrix.json` |
| TC-295-08 | S-92/S-93 conflict, empty, error, export and revoked states pass the viewport/theme gate | 296 / 298 / 299 | `playwright/s92/`, `playwright/s93/export/`, `screenshots/` |
| UX-REF-02 | Approved reference represents every parent state and privacy/legal guardrail | 289, 294, 299 | `playwright/reference_parity.json`, `screenshots/` |

## Acceptance and executable proof matrix

| ID | Requirement | Jira owner(s) | Executable proof | Required evidence path |
|---|---|---|---|---|
| W5-01 | Exact merged-main provenance, clean worktree and scoped changed-file audit | 295, 298 | `git` HEAD/ancestry/status/diff logs | `QA/evidence/SAATHI-295/provenance/` |
| W5-02 | Forward Alembic migration creates `calendar_events`, `calendar_event_sources`, `calendar_conflicts`, `calendar_reminder_preferences`, `calendar_export_subscriptions`, `calendar_export_tokens` and `calendar_export_revocations`, with UUID/FK/index/unique/check/timestamptz constraints | 285, 287, 290, 292, 295, 297, 298 | PostgreSQL 16 upgrade, head/check, schema introspection, downgrade and re-upgrade | `QA/evidence/SAATHI-295/postgres/migration_cycle.log`, `postgres/schema.json` |
| W5-03 | S-90 event aggregation reads real authorised events across supported modules, deduplicates deterministically, preserves source/freshness and excludes cross-user data | 285, 286, 287, 288, 289 | HTTP integration plus browser render from a fresh DB session | `QA/evidence/SAATHI-295/api/events.json`, `playwright/s90/` |
| W5-04 | S-91 creates, reads, updates and deletes personal events through authenticated APIs; browser storage is not authoritative | 285, 286, 287, 288, 289 | API CRUD, refresh/new-context proof, rollback and ownership tests | `QA/evidence/SAATHI-295/api/personal_events.log`, `playwright/s91/` |
| W5-05 | Event instants persist as UTC `timestamptz` with valid retained IANA timezone and deterministic local projection | 285, 287, 288 | timezone/DST parameterised API and direct DB assertions | `QA/evidence/SAATHI-295/postgres/timezone_matrix.json` |
| W5-06 | S-93 reminder preferences are read and updated through real authenticated APIs with server validation, defaults and version-safe/idempotent mutation | 290, 291, 292, 293, 294 | API contract, DB reload and browser refresh | `QA/evidence/SAATHI-295/api/reminder_preferences.log`, `playwright/s93/preferences/` |
| W5-07 | S-92 detects overlaps using half-open `[start,end)` intervals; adjacency is not a conflict; response is deterministic and user scoped | 295, 296, 297, 298, 299 | boundary API matrix plus PostgreSQL query/service tests | `QA/evidence/SAATHI-295/api/conflict_matrix.json`, `playwright/s92/` |
| W5-08 | Concurrent personal-event/conflict operations cannot create duplicate source rows, lose updates or disclose another user's events | 285, 287, 288, 295, 297, 298 | PostgreSQL multi-connection race tests | `QA/evidence/SAATHI-295/postgres/concurrency.json` |
| W5-09 | Export creation is idempotent; only one active capability survives required rotation semantics; conflicting idempotency reuse fails typed and closed | 295, 297, 298 | HTTP replay/conflict and PostgreSQL race tests | `QA/evidence/SAATHI-295/api/export_idempotency.log`, `postgres/export_race.json` |
| W5-10 | Export capability is 256-bit opaque; only keyed hash/version/status/expiry metadata persists; default expiry is 90 days and configuration driven | 295, 297, 298 | entropy/format tests, direct DB inspection, configured-boundary tests | `QA/evidence/SAATHI-295/privacy/token_storage.json` |
| W5-11 | Public feed fetch accepts a valid active unexpired token, returns valid RFC 5545 content and rejects unknown/expired/revoked/rotated tokens without enumeration | 295, 296, 297, 298, 299 | public HTTP route and an independent ICS parser/subscriber | `QA/evidence/SAATHI-295/ics/feed_contract.log`, `ics/parsed_feed.json` |
| W5-12 | Feed headers include `Referrer-Policy: no-referrer` and `Cache-Control: private, no-store`; raw token never appears in logs, audit, errors, storage, screenshots or sealed evidence | 295, 297, 298 | header assertion plus canary-backed privacy scanner | `QA/evidence/SAATHI-295/privacy/public_feed_scan.json` |
| W5-13 | ICS export uses an explicit allowlist, pseudonymous UID and contains no restricted notes, evidence URLs, private IDs, enrolment/mobile/email or secret fields | 295, 297, 298 | seeded canaries in every forbidden field and parsed-property audit | `QA/evidence/SAATHI-295/ics/privacy_allowlist.json` |
| W5-14 | Rotation/revocation is authenticated, user scoped, immediately invalidates the prior capability and creates a durable audited state transition without raw capability | 295, 296, 297, 298 | API, fresh transaction, public-fetch and audit-row tests | `QA/evidence/SAATHI-295/api/export_lifecycle.log`, `privacy/audit_scan.json` |
| W5-15 | Anonymous, wrong-role and cross-user operations return typed non-enumerating 401/403/404 responses with no mutation | 285, 288, 290, 293, 295, 298 | complete authorisation matrix | `QA/evidence/SAATHI-295/api/authorization_matrix.json` |
| W5-16 | Injected commit/provider/serialization failures roll back atomically; retry is safe and produces no duplicate event/conflict/export/audit state | 285, 287, 288, 290, 292, 293, 295, 297, 298 | failpoint tests plus before/after DB counts | `QA/evidence/SAATHI-295/postgres/rollback_matrix.json` |
| W5-17 | S-90–S-93 loading, empty, partial, error, retry, validation, conflict, export-created, expired, rotated and revoked states match the approved mapping and never fabricate integration success | 286, 289, 291, 294, 296, 299 | React tests plus real API Playwright journeys | `QA/evidence/SAATHI-295/playwright/state_matrix.json` |
| W5-18 | Mobile/desktop light/dark layouts have no unintended horizontal overflow, meaningful mobile scroll, >=44 px targets, keyboard/focus/ARIA support and zero unexpected console/page/network errors | 286, 288, 289, 291, 293, 294, 296, 298, 299 | Chromium at 390/430/768/1024/1440, axe, keyboard and screenshot oracle | `QA/evidence/SAATHI-295/playwright/geometry_a11y.json`, `screenshots/` |
| W5-19 | No raw mobile, email, enrolment, notes, evidence URLs, event private IDs, capability token or secrets leak through DB projections, logs, audit, URLs (except the designated public route), browser storage or errors | 288, 293, 298 | fail-closed canary-backed privacy scanner | `QA/evidence/SAATHI-295/privacy/full_scan.json` |
| W5-20 | Existing registration and Waves 1–4 remain green on the exact Wave 5 commit | 288, 293, 298 | full backend/frontend/CI regression matrix | `QA/evidence/SAATHI-295/regression/` |
| W5-21 | No Google/Outlook OAuth or bidirectional sync is claimed; unavailable controls state truthfully that this release supports iCalendar subscription only | 295, 296, 297, 298, 299 | source audit, UI assertion and network allowlist | `QA/evidence/SAATHI-295/scope/ics_only.json` |

## Release gate

No row may be inferred from a neighbouring row. A release classification of
PASS requires every applicable row to contain raw exact-commit evidence and a
verified checksum. A blocked target runtime remains BLOCKED and is never
relabeled PASS. See the report template and lifecycle section in the evidence
folder.
