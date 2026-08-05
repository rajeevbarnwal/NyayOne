# SAATHI-60 internship discovery closure evidence

Date: 2026-08-03 (Asia/Kolkata)

Scope: SAATHI-60 and children SAATHI-110, SAATHI-111, SAATHI-112,
SAATHI-113 and SAATHI-392.

The evidence in `real-target-runtime/` was generated against the production
frontend and API with no request stubs. The journey used PostgreSQL 16.14 with
pgvector, real registration and login OTP endpoints, an HttpOnly student
session cookie, and headless Chromium.

## Closure matrix

| Area | Result | Evidence |
|---|---:|---|
| Complete backend regression | 1,090 passed, 2 unrelated environment-gated skips | External raw JUnit: `QA/saathi60_final_2026-08-03/logs/backend_full_final.xml` |
| Complete frontend regression | 695 passed, 0 failed | External raw JSON: `QA/saathi60_final_2026-08-03/logs/frontend_full_after_ci_readiness_repair.json` |
| Typecheck, lint, build | PASS | Executed on the final source tree |
| Alembic | upgrade → downgrade → upgrade → no drift PASS | Head `0014_saathi60_internships` |
| PostgreSQL schema | PASS | PostgreSQL 16.14, pgvector present, zero schema failures |
| Concurrent duplicate save | PASS | Two competing writes produce `[False, True]`, one row, one audit event |
| Real HTTP/browser journey | 275/275 PASS | `real-target-runtime/results.json` |
| Application screenshots | 40 captured | `real-target-runtime/screenshots/` |
| Full S-11–S-26 responsive/a11y regression | 1,467/1,467 PASS, 204 screenshots | External sealed run: `QA/saathi60_final_2026-08-03/playwright/v34-stub-exact-final2/` |
| Privacy | PASS | No raw OTP/mobile/session cookie in logs or browser storage; sent OTP ciphertext erased; audit snapshots contain no sensitive keys |

## Functional acceptance

- S-20 reads the catalogue from the API and filters the real response.
- S-21 uses the selected listing identity; Menon and Vidhi never fall back to
  the CAM fixture.
- Verification badge and provenance are projected from one structured status.
  CAM is verified; sample fixtures remain explicitly unverified.
- The CAM source is a structured HTTPS source link with retrieval and
  verification timestamps.
- Saved internships are persisted in `saved_internships`, scoped to the
  authenticated student, and survive a fresh browser context.
- Anonymous and authenticated non-student users receive truthful access
  states; no local success is fabricated.
- S-26 is driven by a genuinely empty server response rather than a hidden or
  hard-coded state.
- S-21 → S-22 → S-23 preserves the exact listing identifier.
- Desktop users can reach all listings; the native disclosure remains closed
  and compact on mobile and open at widths of 821px and above.

## Negative results

| Input/state | Expected rejection or safe result | Actual |
|---|---|---|
| Missing S-21 listing query | Unavailable state; no CAM fallback | PASS |
| Unknown listing slug | HTTP 404 and unavailable state | PASS |
| Uppercase, underscore, empty/path-invalid or >64-character slug | HTTP 422/route rejection | PASS |
| Anonymous saved-list access | HTTP 401 / sign-in state | PASS |
| Authenticated non-student saved-list access | HTTP 403 / student-only state | PASS |
| Duplicate save replay | Idempotent; one row and one audit event | PASS |
| Two simultaneous PostgreSQL saves | One created and one replay result | PASS |
| Cross-user saved-list read | No other student's row visible | PASS |
| Injected commit failure | Saved row and audit event both roll back | PASS |
| Search with no match | Truthful empty search result | PASS |
| Application cover note 49 / 50 characters | 49 rejected; 50 accepted | PASS |
| Non-PDF / empty PDF / 5MB+1 | Rejected; exact 5MB accepted | PASS |
| Horizontal overflow / target below 44px | Zero overflow; no undersized visible target | PASS |
| WCAG A/AA axe scan | Zero violations in the committed viewport matrix | PASS |
| Console, page, request, HTTP or unmatched-API errors | Zero | PASS |

## Remote-gate readiness correction

The first push-triggered Wave 5 browser run exposed a genuine S-91
create-transition race: the old generic ready marker could still describe the
create view while the newly routed event-detail GET was starting. A reload
then surfaced that request as `net::ERR_ABORTED`; the runtime oracle correctly
failed 304/305 rather than hiding it.

The final runner registers the POST 201 and successful detail GET before the
create action, awaits `response.finished()` for both, reconciles the POST body
id, route id and detail URL, and waits for an application-owned readiness
marker keyed to the new event id before reloading. The seeded old sequence
reproduces the abort, while the corrected contract fails closed on a wrong id,
query-bearing URL, non-200 response or aborted response body. It contains no
fixed sleep, `ERR_ABORTED` exception, error-array clearing or assertion-count
change.

## Database ownership

- `internship_listings`: public catalogue content, money in integer paise,
  status, deadline and structured source provenance.
- `saved_internships`: only `user_id`, `listing_id`, UUID/timestamps and the
  normal null metadata field; unique per user/listing with cascading indexed
  foreign keys.
- `audit_events`: append-only `internship.saved` and `internship.unsaved`
  events containing the public listing slug and boolean state, never mobile,
  OTP, email or session-token material.

`real-target-runtime/SHA256SUMS.txt` verifies the 40 screenshots and machine
results. CI regenerates and uploads the full S-11–S-26 browser package so the
reviewer can compare evidence from the exact remote hash.
