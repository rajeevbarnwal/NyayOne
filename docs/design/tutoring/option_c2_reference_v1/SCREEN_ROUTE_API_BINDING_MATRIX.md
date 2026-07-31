# Screen / route / API binding matrix

**Rule applied throughout: no API name is invented.** Where a Priority 2 contract does not yet
exist, the binding column says `PENDING_PRIORITY2_CONTRACT` and names the *obligation*, not an
endpoint, method, field or event.

## 1. Canonical screens and routes

| Screen | Canonical route | Feature state | Owner ticket | Layout family | States |
|---|---|---|---|---|---:|
| S-31 | `/s-31` | `tutors/discovery` | SAATHI-125 → SAATHI-65 | `list` | 3 |
| S-32 | `/s-32` | `tutors/profile` | SAATHI-125 → SAATHI-65 | `profile` | 2 |
| S-33 | `/s-33` | `tutors/book-pay` | SAATHI-125 → SAATHI-65 | `checkout` | 19 |
| S-34 | `/s-34` | `tutors/confirmation` | SAATHI-125 → SAATHI-65 | `receipt` | 6 |
| S-35 | `/s-35` | `tutors/sessions` | SAATHI-129 → SAATHI-66 | `manage`, `prejoin`, `room` | 52 |

`PRODUCT_APPROVED` (route and feature-state names: SAATHI-125 description, mapping reconciliation
2026-07-19). Total 82 states — see `STATE_INVENTORY.json`.

Reference addressing is `reference/index.html?state=<stateId>`; it is a reviewer harness, not a
product route. `&theme=dark`, `&landscape=1` and `&chrome=1` are reviewer switches only.

## 2. Data and behaviour bindings

| Screen | UI obligation | Server authority | Binding status |
|---|---|---|---|
| S-31 | Search, practice-area filter, result list with fee, empty state with recovery | Result set, ranking and fee are server-owned; the client never computes price or eligibility | `PENDING_PRIORITY2_CONTRACT` — obligation only |
| S-32 | Identity, verification, experience, languages, rating, fee, duration, bio, timezone-labelled availability with available/held/booked | Slot status and the 10-minute hold TTL are server-owned; slot ids are immutable and timezone-aware | `PRODUCT_APPROVED` behaviour (D-07), `PENDING_PRIORITY2_CONTRACT` binding |
| S-33 | Order summary, live hold countdown, provider-hosted card fields, authentication challenge, typed outcomes, idempotent retry | Payment state changes only on a server-verified provider event; hold TTL and slot lock are server-owned; money is integer paise | `PRODUCT_APPROVED` behaviour (D-05, D-06, D-07, D-08), `PENDING_PRIORITY2_CONTRACT` binding |
| S-34 | Confirmed status, date/time with timezone, join eligibility, receipt, reminders | Confirmation is rendered only from a server-verified booking; join eligibility is a server decision, never a client clock comparison | `PRODUCT_APPROVED` behaviour (D-08, D-10), `PENDING_PRIORITY2_CONTRACT` binding |
| S-35 management / refund | Policy preview, cancellation, reschedule, refund lifecycle, stale-state refusal | Eligibility, refund amount and settlement are computed server-side from the frozen policy; refunds are idempotent by refund reference | `PRODUCT_APPROVED` behaviour (D-09), `PENDING_PRIORITY2_CONTRACT` binding |
| S-35 pre-join / room | Device test, permission and eligibility refusals, live room controls, network states, leave | Join eligibility, credential lifetime and ownership are server decisions; the client never grants itself entry | **`PENDING_PRIORITY2_CONTRACT` (W2-9)** — no provider, SDK, transport, credential format or event name is asserted |
| S-35 attendance | Pending / marked / confirm / dispute / resolution / resolved / typed refusals | Attendance and completion authority | **`PENDING_PRIORITY2_CONTRACT` (W2-6)** — the reference shows the UI obligation and carries an in-UI notice that the labels are not an approved API |
| S-35 review | 1–5 stars, 10–1,000 characters, moderation notice | Review eligibility requires a server-confirmed attendance record; limits and moderation are server-enforced | `PRODUCT_APPROVED` behaviour (D-12), `PENDING_PRIORITY2_CONTRACT` binding |

## 3. Typed identifiers used in the reference

| Identifier | Provenance |
|---|---|
| `HOLD_EXPIRED`, `DUPLICATE_SUBMIT` | `PRODUCT_APPROVED` — present verbatim in the approved Option C frames |
| Every other identifier in `STATE_INVENTORY.json` | `PROPOSED` — marked `(PROPOSED label)` at the point of use; must be reconciled against the Priority 2 contract before any implementation |

## 4. Explicit non-bindings

- No endpoint path, HTTP method, request/response field, webhook, queue, table or event name
  appears anywhere in this package.
- No payment provider, video provider or SDK is named.
- Nothing in this package may be cited as evidence that an API exists.
