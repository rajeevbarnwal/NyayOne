# NYAY-30 fixture-key alphabet sweep

Base for this corrective cycle: `166a191b9cfa3e77d24e223db55716a438255b2e`.
The authoritative grammar is `profile-key-alphabet.v1`, alphabet
`-0123456789abcdefilopr`, length 16–200. No service or product code changes.

## Scope and disposition

The repository search covers idempotency-key references in backend/scripts,
backend/tests, frontend/scripts and frontend/src, plus profile mutation sinks.
The publication inventory records every matching file and source line; references
include generators, forwarded arguments, declarations, and negative assertions.
This is a service-aware sweep, not a universal change to unrelated key grammars.

| Surface | Generator / receiving contract | Disposition |
| --- | --- | --- |
| NYAY-5 browser | `profileFixtureIdempotencyKey`, 3 direct profile PATCH header sites | Only remaining invalid positive profile generator: replace old prefix with `profile-`, retaining 24 random bytes, hex encoding, privacy registration, and distinct-call behavior. |
| NYAY-2 native | `_profile_mutation_headers` | Already corrected: profile prefix plus SHA256 of stable probe label; duplicate Origin headers/replay preserved; 21 assertions unchanged. Signup/reviewer keys use separate services. |
| NYAY-5 native | Injected profile mutation helper | Already corrected: profile prefix plus UUID hex. Credential/share/reviewer/legacy-record fixtures are separate contracts and unchanged. |
| NYAY-9 native | Seven positive profile examples; shared/replay/concurrency keys | Already conformant; exact shared-vs-distinct relationships retained. |
| Profile HTTP tests | `tests/profile_idempotency_fixture.py`, NYAY-5/9 positive HTTP fixtures | Already conformant. Missing/duplicate/short/PII/legacy-alphabet rejection examples remain intentionally invalid. |
| Wave-1 browser | Profile projection/readiness mocks; shipped UI generator | No independent positive profile key generator. Product UUID/profile-hex generator remains unchanged. |
| Wave-3 | Credential/reviewer keys, registration seed, S-01–S-10 signup keys | Separate credential/registration services, not profile grammar; retain rejection and authorization checks. |
| Wave-5 | Calendar export/rotation keys; registration/credential seeds | Separate calendar/registration/credential contracts; unchanged. |
| NYAY-17 / registration | Registration request, ledger, migration and provider idempotency examples | Separate registration validator and legacy migration records; unchanged. Do not rewrite stored legacy values or negative probes. |
| NYAY-3/4/8/16 native/tests | Registration, OTP delivery and legacy schema fixtures | No additional positive profile HTTP generator; unchanged. |
| NYAY-19 / retention | Data-subject request keys, registration ledger/erasure fixtures | Separate deletion/registration or stored-record semantics; unchanged. |
| NYAY-22 mentor | Ceremony operation keys and mentor ledger hashes | Separate mentor grammar; no client-authority, role, erasure or idempotency changes. |
| NYAY-11 reviewer | Reviewer/guardian/authority mutation keys | Separate authority commands; no authorization or conflict-metadata change. |
| Wave-2/4 and worker fixtures | Booking, payment, reporting, moderation, risk-label, job/outbox keys | Different receiving services; not profile mutation generators; unchanged. |
| Profile legacy service/lifecycle tests | Legacy replay ledger and credential/projection fixtures | Preserve historical values and rejection checks; these are not new positive owner-profile API keys. |

## Tests-first proof

The new backend contract executes the actual JavaScript browser helper under
four controlled entropy patterns and validates its output with the real profile
service validator. RED: 4 failures and 6 preservation passes. GREEN: 10/10.
Legacy prefixes continue to produce the typed privacy-safe rejection. The three
profile header call sites, registration's separate fixture, setup failure oracle,
cryptographic entropy and privacy registration are preserved. Combined focused
NYAY-30/32/native/browser fixtures: 54/54.

No 22-row browser inventory, geometry/accessibility/runtime/privacy assertion,
negative key case, native inventory, product source, or workflow is weakened.

## Exact seals

Only this cycle's browser seal changes:

`EXPECTED_NYAY5_BROWSER_GATE_SHA256`

`5ce8b7100bd49603ff0ae97bc2f1ee4e1ab7a851a252be70854d32afb7a1fe82`
→ `5ec659792697230444aa21b1d59fd93a1b389ad557b82386e13aca921d2db783`.

Earlier PR #29 native fixture seal, retained unchanged by this cycle:

`EXPECTED_NYAY5_POSTGRES_GATE_SHA256`

`951acff76919333e8446aed279309d887e350bcfed19c194f2991fe892ddd1c5`
→ `6d659081ec06b7c8e5fc0e213b2453e25520e04cd9e626f40c4d508fb2241197`.

NYAY-2 and NYAY-9 have no corresponding producer seal change. No other reseals.
NYAY-21 remains HOLD/NO-GO. No runner routing, visibility or ruleset change.
