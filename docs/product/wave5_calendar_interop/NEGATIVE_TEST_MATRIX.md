# Wave 5 — Mandatory Negative and Boundary Matrix

Initial result for every case: **NOT EXECUTED**. The executor must record exact
input, expected failure, actual HTTP/UI/DB outcome, mutation counts and raw
evidence path. “Covered by unit tests” is not an acceptable result.

## Event and temporal validation

| ID | Input/action | Expected failure or outcome | Owner |
|---|---|---|---|
| N-01 | Empty title, whitespace title | 422 typed validation; no row/outbox/audit mutation | 287/288 |
| N-02 | Title at configured maximum and maximum + 1 Unicode character | Maximum accepted; +1 rejected without truncation | 287/288 |
| N-03 | Control characters/HTML/script/emoji/special characters in title | Invalid controls rejected; permitted Unicode encoded safely; never executable | 287/288 |
| N-04 | Missing/invalid `start_at`, `end_at` or timezone | 422 typed validation; no silent replacement | 287/288 |
| N-05 | `end_at < start_at` and zero-duration event | Rejected per contract; no mutation | 287/288 |
| N-06 | Valid IANA timezone; invalid name; DST ambiguous and non-existent local time | Valid accepted; invalid/ambiguous/non-existent handled by explicit typed policy, never silently shifted | 287/288 |
| N-07 | Adjacent A `[10:00,11:00)` and B `[11:00,12:00)` | No conflict | 297/298 |
| N-08 | 1 ms overlap, exact duplicate interval, containment and multi-event overlap | Conflict with deterministic stable ordering and no cross-user data | 297/298 |
| N-09 | Very old/future valid date and storage/database boundary | Explicit supported boundary accepted; out-of-range rejected typed | 287/288 |
| N-10 | Duplicate source event and same source ID in different source types | Exact source tuple deduped; distinct source type retained | 287/288 |

## Authentication, ownership and enumeration

| ID | Input/action | Expected failure or outcome | Owner |
|---|---|---|---|
| N-11 | No authenticated session | 401; no data or mutation | 288/293/298 |
| N-12 | Wrong actor role | 403; no mutation | 288/293/298 |
| N-13 | User A reads/updates/deletes user B event/preferences/export ID | Non-enumerating 404 (or frozen typed policy); no B data leaked | 288/293/298 |
| N-14 | Forged actor header in staging/production | Rejected; cannot override cookie-backed actor | 288/293/298 |
| N-15 | Unknown resource ID versus another user's resource ID | Indistinguishable status/body/timing within test tolerance | 288/293/298 |

## Reminder preferences

| ID | Input/action | Expected failure or outcome | Owner |
|---|---|---|---|
| N-16 | Empty/missing preference payload | Explicit defaults or typed rejection; never partial overwrite | 292/293 |
| N-17 | Lead time outside `[0, 10, 30, 60, 120, 1440]`, duplicate source/channel pair | Only the canonical minute values and one row per source/channel accepted | 292/293 |
| N-18 | Quiet minute `-1`, `0`, `1439`, `1440`; unknown channel/source; invalid timezone | 0 and 1439 accepted; -1/1440 and unknown values rejected typed | 292/293 |
| N-19 | Stale version/concurrent updates | One deterministic winner or typed conflict; no lost update | 292/293 |
| N-20 | Injected commit failure | Old preferences remain; retry succeeds once | 292/293 |

## Export capability and public feed

| ID | Input/action | Expected failure or outcome | Owner |
|---|---|---|---|
| N-21 | Reuse same idempotency key and identical request | Same export result; no duplicate active token/audit | 297/298 |
| N-22 | Reuse same key with different payload | Typed idempotency conflict; no mutation | 297/298 |
| N-23 | Concurrent export create/rotate requests | Contract-defined single active capability; no orphan/duplicate rows | 297/298 |
| N-24 | Capability shorter than 256 bits, malformed/base64/Unicode/path traversal token | Non-enumerating 404; no parser/stack trace/log disclosure | 297/298 |
| N-25 | Unknown, expired, revoked, rotated-old and valid token | Invalid states indistinguishable; valid returns feed only | 297/298 |
| N-26 | Expiry at now-1 ms, exactly now and now+1 ms | Frozen inclusive/exclusive expiry boundary applied consistently | 297/298 |
| N-27 | Raw token inserted as a canary in exception/log/audit/evidence path | Scanner detects and fails the gate | 297/298 |
| N-28 | Raw token stored in DB column or browser local/session storage | Gate fails; only keyed hash plus bounded metadata allowed | 297/298 |
| N-29 | Feed request with query string or capability in non-designated URL | Rejected/redirect-free; no token copied elsewhere | 297/298 |
| N-30 | Attempt OAuth/sync provider call in this release | No provider request; truthful ICS-only UI state | 296/297/298/299 |

## ICS correctness and privacy

| ID | Input/action | Expected failure or outcome | Owner |
|---|---|---|---|
| N-31 | Comma/semicolon/backslash/newline/non-ASCII in allowed text | Valid RFC 5545 escaping/folding and round-trip parse | 297/298 |
| N-32 | Very long property requiring line folding | Valid UTF-8-safe 75-octet folding; parser round-trips | 297/298 |
| N-33 | Seed mobile, email, enrolment, private DB ID, note and evidence URL canaries | None appears in parsed or raw feed | 297/298 |
| N-34 | Restricted event source | Privacy-minimised title/projection or omission per source policy | 287/288/297/298 |
| N-35 | Empty calendar | Valid empty VCALENDAR, never malformed/500 | 297/298 |
| N-36 | Duplicate events and pseudonymous UID stability | No duplicate VEVENT; UID stable where required and non-reversible | 297/298 |
| N-37 | Feed response headers | Exact no-referrer and private/no-store headers present | 297/298 |

## UI, accessibility and resilience

| ID | Input/action | Expected failure or outcome | Owner |
|---|---|---|---|
| N-38 | API loading/empty/partial/error/retry | Truthful distinct state; retry only failed dependency where specified | 286/289/291/294/296/299 |
| N-39 | Conflict appears/disappears after refresh or edit | Server result wins; no stale local-only success | 296/299 |
| N-40 | Expired/revoked export viewed in S-93 | Clear unavailable state; rotate/create path accessible | 296/299 |
| N-41 | Keyboard-only, focus restoration, Escape, screen reader names | Logical focus/order, no traps, stable accessible names | 286/289/291/294/296/299 |
| N-42 | Tooltip-mandated help | Accessible info icon + hover/focus tooltip; not unexplained static helper text | 286/289/291/294/296/299 |
| N-43 | 390/430 px, 200% zoom, reduced motion, safe areas | No unintended horizontal overflow/clipping; >=44 px targets; meaningful mobile scroll | 286/289/291/294/296/299 |
| N-44 | Browser refresh/new context after mutation | State reloads from API/PostgreSQL, not browser storage | 286/288/291/293/296/298 |

## Failure, rollback and privacy canaries

| ID | Input/action | Expected failure or outcome | Owner |
|---|---|---|---|
| N-45 | Inject failure before/after flush and before commit | Entire mutation rolls back; no audit/outbox orphan | 287/288/292/293/297/298 |
| N-46 | Retry after rollback/provider failure | Exactly one durable result and audit transition | 287/288/292/293/297/298 |
| N-47 | Parallel event create/update/delete/conflict/export | Required uniqueness/version invariants hold on PostgreSQL | 288/293/298 |
| N-48 | Seed forbidden canaries into DB, logs, audit, URL, storage, console and error | Scanner proves it can detect each canary; clean run has zero findings | 288/293/298 |
| N-49 | Existing registration/Waves 1–4 suites | Zero newly introduced failure; raw counts sealed | 288/293/298 |

## Mandatory legacy registration regression (unchanged-feature guard)

Wave 5 does not own registration fields, but the full regression gate must
explicitly re-run these cases rather than infer them from a generic suite.

| ID | Input/action | Expected failure or outcome | Owner |
|---|---|---|---|
| N-50 | Mobile with 9 digits and 11+ digits | Both rejected by strict exact-10-digit validation; no OTP/session mutation | 298 |
| N-51 | Historical/DOB input `2030-01-01` | Future date blocked with a clear field error; submission blocked | 298 |
| N-52 | Empty, special-character and exact maximum/+1 first/middle/last names | Required/name-character/max rules apply to the correct sub-field; no silent truncation | 298 |
| N-53 | Institutional email, college and enrolment identifiers in the legacy journey | Fields remain present and correctly mapped; a missing field is a Critical Regression | 298 |
| N-54 | Split first/middle/last names through UI -> HTTP -> database projection | Payload mapping preserves each component; validation is not applied to the wrong field | 298 |
| N-55 | Mandated helper affordance | Accessible info icon and hover/focus tooltip exist; static helper text alone fails | 298 |

## Required result columns

The executed report must add: exact commit, runtime, input fixture, expected
status/error, actual status/error, before/after row counts, PASS/FAIL/BLOCKED,
raw log path and checksum. Missing columns make the case `NOT EXECUTED`.
