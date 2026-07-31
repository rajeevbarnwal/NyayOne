# Wave 2 Tutoring — FROZEN AC/TC CLOSURE MATRIX

Owner: Senior Engineer (integration owner). Frozen before implementation.
Base: `origin/main` = `93dc58523accb48c7fdd7da78e6e26a7c35d7060` (contains PR #6 `57e61b0`
and PR #7 `8230f5c`; approved reference package `docs/design/tutoring/option_c2_reference_v1`
is on main). Branch: `engineer/wave2-production-saathi-65-66`.
Alembic head on main: `0007_wave3_credentials` → this wave adds `0008_wave2_tutoring`.

## Provenance correction (binding)

A previous cycle reported Wave 2 source/tests and a "131 passing" result. Independent
inspection proved the branch still equalled `93dc585`, the sandbox worktree was gone and
no files existed in the persistent repository. **That evidence is withdrawn and is NOT
cited anywhere in this wave.** Everything below is rebuilt from `origin/main` in a
persistence-proven worktree (inside the mounted repo, shared `.git`), with a cohesive
checkpoint commit after every work package so a sandbox/API failure cannot destroy work.

## Frozen Product decisions (quoted, not reinterpreted)

Source: SAATHI-65/66 comments 12794/12796, 12816/12817, 12933 and SAATHI-451.

1. SAATHI-65 owns canonical S-31–S-34. 2. SAATHI-66 owns canonical S-35 (older S-22–S-26
tutoring mappings superseded). 3. Provider-neutral `PaymentProvider`. 4. Razorpay first
production adapter; deterministic adapter for automated/local. 5. **Never** send/persist
full PAN, CVV or payment OTP in APIs, PostgreSQL, logs, audit, URLs or browser storage —
provider-hosted/tokenised fields only; persist provider refs/tokens, brand, masked last4,
permitted expiry metadata, amount/currency/status, timestamps. 6. Hold default 10 minutes,
configurable. 7. Only a **verified provider payment event** converts a hold into a session;
failure/expiry releases the slot. 8. INR stored as **integer paise**, never float.
9. Student cancel/reschedule ≥24h = full refund / free reschedule; <24h = no automatic
refund, authorised **audited admin exception**; tutor cancellation = full refund.
10. Tutor/admin record attendance/completion **only after scheduled end**; student confirms
or disputes; admin resolves; reviews blocked while attendance absent or disputed.
11. Review: integer 1–5; optional text 10–1000 chars; one per session; editable 7 days;
user-deletable; public aggregates from published reviews only. 12. Written reviews require
moderation; rating contributes publicly only after approval. 13. Instants UTC `timestamptz`
+ retained IANA timezone; test ambiguous/non-existent DST. 14. Reminders 7d/1d/3h;
reschedule/cancel revokes stale jobs; durable outbox. 15. Config-driven rate limits: search
60/min, booking/payment mutations 10/min, review mutations 5/hour per user. 16. Slot
allocation atomic/row-locked: one winner, identical idempotency replay returns the same
result, competitor gets a typed conflict. 17. Provider-neutral `VideoSessionProvider`.
18. Join credentials opaque, short-lived, participant/room/permission-bound, authorised
paid participants only. 19. Deterministic adapter mandatory for business-contract
automation. 20. `LiveKitCommunityAdapter` first deployable adapter behind the contract.
21. No raw join token, provider secret, SDP, ICE candidate, media, private narrative or
device label persisted or logged.

## Ownership map (no requirement ownerless, no duplicate ownership)

| # | Requirement | Ticket | FE route/state | HTTP route | Service/provider | PG table/constraint | Positive test | Negative/boundary | Failure/concurrency | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| A1 | Tutor discovery + filters/sort/pagination | 123 (api) / 122 (ui) | `/s-31` schools-like `tutoring/search` | `GET /api/v1/tutors` | `tutoring.availability.search_tutors` | `tutor_profiles`, `tutor_subjects` (+FK idx) | list/filter/sort/page | empty/unsupported/over-length filters | rate limit 60/min | `test_wave2_discovery.py`, PW `s31_*` |
| A2 | Tutor detail + verified claims/provenance | 123/122 | `/s-32` `tutoring/detail` | `GET /api/v1/tutors/{id}` | `availability.get_tutor` | `tutor_profiles` | detail render | unknown id non-enumerating 404 | — | same |
| A3 | Availability + timezone | 123/122 | `/s-32` | `GET /api/v1/tutors/{id}/availability` | `availability.list_slots` | `tutor_availability_slots` (status CHECK) | slots + tz | invalid date/tz; **DST ambiguous + non-existent**; stale availability | — | `test_wave2_discovery.py` |
| B1 | Booking hold (10 min, configurable) | 123/122 | `/s-33` `tutoring/hold` | `POST /api/v1/tutoring/booking-holds` | `booking.create_hold` | `booking_holds` (status+expiry CHECK, uniq idempotency, uniq active slot) | hold created | expired hold; different key vs consumed slot | **8+ concurrent → 1 winner + typed conflict**; commit failure | `test_wave2_booking.py` |
| B2 | Hold read | 123/122 | `/s-33` | `GET /api/v1/tutoring/booking-holds/{id}` | `booking.get_hold` | `booking_holds` | read | cross-user non-enumerating | — | same |
| C1 | Payment order (tokenised) | 123/122 | `/s-33` payment | `POST /api/v1/payments/orders` | `payments.create_order` + `PaymentProvider` | `payment_orders` (amount_paise≥0 INT, currency CHECK, uniq idempotency) | order created | **no PAN/CVV/OTP anywhere** | provider unavailable/timeout | `test_wave2_payments.py`, privacy scan |
| C2 | Verified webhook → session | 123 | — | `POST /api/v1/payments/webhook` | `payments.handle_event` | `payment_events` (uniq provider event id) | verified event books session | malformed/invalid-signature/duplicate/out-of-order; mismatched amount/currency/order/user; **payment after hold expiry** | replay protection; commit failure | same |
| C3 | Session creation only on verified payment | 123 | `/s-34` | `POST /api/v1/tutoring/sessions` | `sessions.create_from_paid_hold` | `tutoring_sessions`, `booking_events` | session confirmed | unpaid/unverified rejected | atomic w/ hold consumption | same |
| D1 | Session list/detail | 127/126 | `/s-35` list, `/s-34` detail | `GET /tutoring/sessions[/{id}]` | `sessions.list/get` | `tutoring_sessions` | render | cross-user isolation | — | `test_wave2_sessions.py` |
| D2 | Reschedule (≥24h free) | 127/126 | `/s-35` | `POST …/{id}/reschedule` | `sessions.reschedule` | `session_status_history`, `session_reminder_jobs` (revocation) | ≥24h free | <24h policy; exactly-24h boundary | stale version; reminder revocation | same |
| D3 | Cancel + refund policy | 127/126 | `/s-35` | `POST …/{id}/cancel` | `sessions.cancel` + `payments.refund` | `session_cancellations`, `payment_refunds` (uniq per order) | ≥24h full refund | <24h no auto refund; **audited admin exception**; tutor cancel full | partial/duplicate refund prevention | same |
| D4 | Completion after scheduled end | 127 | `/s-35` | `POST …/{id}/complete` | `attendance.record` | `session_attendance` (one per session, `version`) | after end ok | **early completion rejected**; wrong role; cross-user; stale version | — | same |
| D5 | Attendance confirm/dispute/resolve | 127/126 | `/s-35` | attendance confirm/dispute/resolve | `attendance.confirm/dispute/resolve` | `session_attendance` state CHECK | lifecycle | student dispute; admin resolution | stale version | same |
| E1 | Join credentials | 127/126 | `/s-35` live room | `POST …/{id}/join-credentials` | `VideoSessionProvider.issue` | `video_session_grants` (expires_at>issued_at, **no raw token column**) | authorised paid participant | unauthorised; wrong room/participant/permissions; expired/revoked/replayed | provider unavailable | `test_wave2_sessions.py`, privacy scan |
| E2 | Video webhook | 127 | — | video webhook | `VideoSessionProvider.verify_event` | `session_status_history` | verified event | invalid signature; duplicate/idempotent | — | same |
| F1 | Review create/edit/delete | 127/126 | `/s-35` review | review endpoints | `reviews.create/edit/delete` | `tutor_reviews` (uniq per session, rating 1–5 CHECK, text 10–1000 CHECK) | 1–5 + optional text | **rating 0/6/non-integer; text 0/9/10/1000/1001**; duplicate; edit after 7 days; cross-user | commit failure no partial write | `test_wave2_reviews.py` |
| F2 | Review gating on attendance | 127 | `/s-35` | review create | `reviews.assert_reviewable` | — | allowed when confirmed | **blocked while absent/disputed** | — | same |
| F3 | Moderation + public aggregate | 127 | `/s-35` moderation state | moderation approve/reject | `reviews.moderate` | `review_moderation` | approve publishes | reject; **aggregate excludes unmoderated**; role enforced | — | same |
| G1 | Durable outbox + reminders | 123/127 | — | — | `outbox_relay`, `reminders` | `tutoring_outbox`, `session_reminder_jobs` | dispatch after commit | outbox failure/retry, no duplicate side effect | post-commit delivery failure | `test_wave2_*` |
| H1 | LiveKit/TURN infra | 451 | — | — | `LiveKitCommunityAdapter` | — | health/readiness, forced-TURN smoke | webhook signature validation | restart/reconnect/provider outage | `infra/` + SBOM/runbook |
| I1 | Browser journeys S-31–S-35 | 124/128 | all | all | all | all | full journey | negative states | reconnect/outage | Playwright traces/screenshots |
| I2 | Geometry/a11y (live room) | 128 | `/s-35` | — | — | — | 100dvh, ≥44px, no overflow | 200% zoom, reduced motion, safe-area | — | browser matrix JSON |
| J1 | Privacy | 123/127/128 | all | all | all | audit/outbox payloads | canaries absent | PAN/CVV/OTP/token/SDP/ICE/device-label scans | — | privacy scan JSON |

## Runtime capability (declared before coding — no gate will be claimed unexecuted)

Available in this environment: Python 3.10 venv, Node 22/npm 10, **real Chromium** (arm64
`libXdamage` stub on `LD_LIBRARY_PATH`), SQLite, Jira (Atlassian integration), persistent
repo mount + shared `.git`.
**Not available:** PostgreSQL 16/pgvector (`psql` absent, no Docker, uid 1001), Docker (so
LiveKit/TURN **runtime** smoke), GitHub SSH/`gh` (so push/PR/CI).
Consequence: PG16 introspection/concurrency, LiveKit runtime smoke and push/PR/CI are
**external-blocked** and will be reported as UNEXECUTED with exact commands for the Mac —
never as PASS, and never substituted by SQLite/service results.
