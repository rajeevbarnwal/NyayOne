# NYAY-11 guardian and institutional authority — implementation and operations

## Scope and authoritative policy

This document describes the NYAY-11 backend and its operational dependencies; it
does not authorize deployment, a production migration, or a retention job run.
The owner policy is Jira comment **14714**, version **NYAY-11-v1**. Its sealed
provenance and complete transition inventory are in
[STATE_MACHINE_CONTRACT.json](STATE_MACHINE_CONTRACT.json). The implementation
entry points are `backend/app/api/v1/student_authority.py`,
`backend/app/services/student_authority.py`, and
`backend/app/models/student_authority.py`.

The 61 outcomes are **25 guardian source/target pairs plus 36 institutional
source/target pairs**, not 61 independently assignable states. Guardian states
are `NOT_REQUIRED`, `REQUIRED_PENDING`, `VERIFIED`, `REJECTED`, and `REVOKED`.
Institutional states are `UNVERIFIED`, `PENDING`, `VERIFIED`, `REJECTED`,
`EXPIRED`, and `REVOKED`. Clients submit scoped commands, never a transition
authority or arbitrary target state.

| Locked policy | Implementation boundary |
| --- | --- |
| P1: server-attested OTP consent and relationship declaration | An adult, separately authenticated NYAY-8 student session accepts or declines a server-created guardian invitation. No external identity provider or student self-approval is substituted. |
| P2: 12-month guardian TTL and immediate guardian/owner revocation | Guardian expiry is `P12M`, calculated as calendar months; the leap-day anniversary clamps to February 28. Current proof checks and explicit revocation do not wait for the worker. |
| P3: verified institutional email plus admin assignment | Both the reviewer and the subject need current institutional email proof; reviewer assignment is scoped to the exact institution and `review` operation. Break-glass is configured-platform-owner-only and audited. |
| P4: timeout returns to queue, never auto-rejects | A due review remains `PENDING`, increments its version, and writes one durable `review_returned_to_queue` notification and aggregate event. |
| P5: explicit legacy mapping, no silent drops | Migration and runtime mapping use a closed registry. Unknown labels fail with `legacy_authority_unmapped`; legacy positive flags are recorded, then require fresh proof. |
| P6: dependent identity changes require reverification | DOB invalidates guardian proof; institutional email invalidates institutional proof. A further mutation of that dependency is blocked while its reproof flag remains set. |

## Canonical API matrix

All paths below include the `/api/v1` mount. Every mutation requires the existing
trusted-Origin check, an authentic server-issued session cookie, and an
`Idempotency-Key` header containing 16–200 characters from
`A–Z a–z 0–9 . _ ~ -`. Keys must be opaque and must not contain personal data.
Every new request and response model forbids extra fields. Boolean fields are
strict booleans. Query parameters are rejected, not treated as owner selectors.
Session identity, role, validity, and target ownership are revalidated server-side
under the command's locks.

All successful operations currently return **HTTP 200**. `Projection` means the
exact six fields `policy_version`, `guardian_state`, `institutional_state`,
`version` (integer, at least 1), `access_mode` (`limited` or `full`), and
`reverification_required` (boolean). `policy_version` is `NYAY-11-v1`.
`access_mode` in this projection reflects the guardian boundary; `full` is not
an institutional approval or blanket authorization for every feature.

| Method and exact path | Exact body fields | Success body | Additional authority |
| --- | --- | --- | --- |
| GET `/api/v1/auth/student/authority` | No body | `Projection` | Own active student registration; read settles current age, proof loss/expiry, and due review timeout. |
| GET `/api/v1/auth/student/authority/notifications` | No body | `{"notifications":[{"code":"review_returned_to_queue","state_version":N}]}` | Own active student registration and canonical session; read settles elapsed timeouts. Other owners' notification rows are not returned. |
| POST `/api/v1/auth/student/authority/guardian/request` | `{}` | `Projection` plus `invitation` | Own pending guardian flow; a new request retires older pending invitations. |
| POST `/api/v1/auth/student/authority/guardian/consent` | `invitation`: string 32–128; `relationship`: `parent` or `legal_guardian`; `accepted`: boolean | `Projection` | Separately authenticated adult student account, distinct from the subject; current, unconsumed invitation generation. |
| POST `/api/v1/auth/student/authority/guardian/revoke` | `registration_id`: optional UUID string; absent/null means own registration | `Projection` | Subject owner or the guardian currently linked to the target. |
| POST `/api/v1/auth/student/authority/institutional/request` | `{}` | `Projection` | Own active student registration; queues review for seven days. |
| POST `/api/v1/auth/student/authority/institutional/review` | `registration_id`: UUID string; `approve`: boolean | `Projection` | Current reviewer email proof and active admin assignment for the target institution; no self-review or cross-institution review. |
| POST `/api/v1/auth/student/authority/institutional/email/request` | `email`: string 3–254; `institution`: string 1–120 | `{"status":"code_sent"}` | Active student/admin/legal-reviewer session; configured institution-domain binding. Student destination must match their saved profile and institution. |
| POST `/api/v1/auth/student/authority/institutional/email/verify` | `code`: exactly six digits | `{"status":"verified"}` | Same authenticated account and active, receipt-backed, unexpired email challenge. |
| POST `/api/v1/auth/student/authority/institutional/assignment` | `reviewer_id`: UUID string; `institution`: string 1–120; `expires_at`: timezone-aware ISO timestamp, at most 40 characters | `{"status":"assigned"}` | Canonical admin session; reviewer already has current proof for that institution. Deadline must be future, at most 365 days away, and no later than proof expiry. |
| POST `/api/v1/auth/student/authority/institutional/break-glass` | `registration_id`: target UUID string | `Projection` | Exact configured platform-owner user and canonical admin session; only the registered revocation transition is available. |

The reusable break-glass body schema permits an omitted target, but the service
does not interpret that as an unscoped action: target resolution fails closed.
UUID syntax is validated before a command acts. None of these commands changes
the NYAY-8 cookie policy or establishes authority in browser storage.

### Compatibility surface

The existing POST `/api/v1/auth/student/verification/status` is not an alternate
approval route. Its body remains `registration_id`, `status`, and
`expected_profile_version`; `Idempotency-Key` is now mandatory for the delegated
command. Only `verified` and `rejected` are accepted as review decisions, with
the same current email-proof, assignment, institution, session, and no-self-review
checks as `/institutional/review`. It additionally enforces the expected profile
version only after verifying institution scope; an unassigned reviewer receives
no version-conflict metadata. The compatibility ledger separately fingerprints
the expected version and preserves the exact successful response on replay.
Success returns `status`, `profile_version`, and
`owner_projection_invalidated: true`. The existing GET in that namespace is a
compatibility status read, not the complete new authority projection.

The legacy guardian self-approval endpoint stays denied. Consumers must use the
new guardian command namespace; exposing a UI button does not grant proof.

### Typed error behavior

Service errors use the existing envelope
`{"detail":{"code":"…","message":"Request failed"},"request_id":"…"}`.
Framework schema failures use `validation_error` and sanitized location/type/
message metadata; rejected input and validation context are omitted. Do not log
request bodies, invitations, email addresses, OTPs, cookies, or provider receipts.

| HTTP status | Code(s) | Meaning |
| --- | --- | --- |
| 401 | `authentication_required` | No usable canonical session at the command boundary. |
| 403 | `authority_denied` | Collapsed role, scope, proof, generation, expiry, or state-authority denial; no target-existence disclosure. Existing Origin middleware may deny earlier. |
| 409 | `authority_state_conflict`, `authority_idempotency_conflict` | Incompatible command state, or the same actor/operation/key with a different scoped payload. |
| 409 | `legacy_authority_unmapped`, `identity_dependency_unknown`, `identity_reproof_required` | Unrecognized legacy/dependency input, or pending dependent reverification. |
| 409 | `authority_delivery_superseded` | Delivery completion no longer matches the stored challenge generation. |
| 422 | `validation_error`, `authority_request_invalid`, `idempotency_key_required`, `invalid_date_of_birth` | Invalid wire shape/header/query, invalid normalized command input, or invalid DOB. |
| 429 | `authority_rate_limited` | Institutional proof resend attempted before the one-minute floor. |
| 503 | `authority_provider_unavailable`, `authority_delivery_pending` | Provider unavailable/no receipt, or replay of a delivery not established as sent. |

The compatibility review route additionally retains `profile_version_conflict`
(409) and collapsed `verification_not_found` (404). Unexpected internal failures
remain generic `internal_error` responses; they are not reported as success.

## Proof ceremonies, replay, and concurrency

Guardian request returns a **manual-handoff invitation**, not a guardian session,
proof, or bearer authorization. It expires after 24 hours and is stored as a
keyed hash bound to the subject and current state generation. The user may hand
it to the intended guardian through an appropriate private channel. It must not
be put in URLs, analytics, browser storage, screenshots, or evidence logs.
Automatic guardian invitation delivery and external relationship verification
are not implemented by this slice.

The guardian authenticates separately using the real NYAY-8 passwordless OTP
flow. Consent requires that canonical session, an active adult registration,
the invitation, a relationship declaration, and explicit acceptance/decline.
The backend consumes the invitation and records consent version
`guardian-consent.v1`, verification time, purpose-specific linkage and expiry.
Proof binds both the child's DOB and a separate domain-HMAC snapshot of the
guardian's own DOB. A guardian DOB change invalidates the child's proof even
when the guardian remains an adult; the subject returns to pending/limited mode
and requires fresh proof.
Possession of the invitation alone is insufficient. An adult account and a
declared relationship are the approved P1 proof mechanism, not a government-ID
or externally verified legal-relationship claim.

Institutional email proof is a separate challenge. The raw code exists only in
memory during generation/provider delivery; the database keeps keyed hashes.
The challenge has a ten-minute lifetime, a one-minute resend floor, and at most
five verification attempts. A successful verify consumes its code hash and
establishes email proof for 365 days. A reviewer decision expires at the earliest
of subject proof expiry, reviewer proof expiry, and assignment expiry.
For a student reviewer, proof must also match that reviewer's current canonical
profile email and institution. A reviewer email change invalidates dependent
institutional approvals and returns those subjects to pending/reproof; an old
provider receipt or assignment alone does not preserve their approval.

Delivery is intentionally not a single database transaction around a network
call: the pending challenge and idempotency outcome are committed before send.
The provider must implement `send_idempotent` and return a receipt. Receipt and
generation checks, followed by canonical session revalidation, precede challenge
activation. Failure does not yield `code_sent`; failed verification attempts are
durable. Operators must handle pending/failed delivery as failure states, not
manually promote them to proof.

Other commands commit state, encrypted replay result, and aggregate event
together. The ledger binds actor, operation, key hash, target scope, and payload
fingerprint. Exact replay returns the recorded response without granting current
authority again; consumers must re-read canonical state after replay. A new
payload with a reused key is a conflict, never a second mutation. Registration,
session, proof and assignment locks serialize effects; paired guardian
registrations and paired email-proof rows use stable ordering. Production proof
of races belongs to the native PostgreSQL gate, not an in-memory timing claim.

## Deployment configuration and scheduled work

The settings below are deployment-controlled, not request-controlled. Pydantic
settings accepts the corresponding uppercase environment names. Configure them
through the deployment secret/configuration facility, never by committing real
owner IDs, email addresses, provider tokens, or institutional registries here.

| Setting | Default and required operation |
| --- | --- |
| `authority_institution_domains` / `AUTHORITY_INSTITUTION_DOMAINS` | Empty dictionary: all institutional proof requests are denied. Supply a reviewed JSON mapping of exact institution identifiers to normalized approved email-domain lists; domain matching is exact, not a suffix wildcard. |
| `authority_platform_owner_id` / `AUTHORITY_PLATFORM_OWNER_ID` | `None`: break-glass denied. Bind one reviewed platform-owner user ID; that account must also hold an active server-issued admin session. Being an arbitrary admin is insufficient. |
| Existing `otp_delivery_enabled`, `otp_provider`, `otp_provider_url`, `otp_provider_supports_idempotency`, `otp_provider_token` | Use the configured real idempotent provider. Missing/disabled/misconfigured delivery fails closed. The provider must actually support institutional email destinations and return its receipt header. The capturing provider is test/testing-only, not a production proof provider. |

Reviewer assignment is performed through the admin command only after the
reviewer's email proof. A registry entry does not by itself assign a reviewer,
and an assignment does not replace email verification. Registry/owner changes
require operational review and audit; no public provisioning API is added here.

The bounded worker entry point is:

```sh
# From an approved deployed backend release, under its managed environment:
python -m app.workers.student_authority
```

This is an **operator-scheduled job**, not an automatic scheduler installed by
the application. `run_once(session, now=..., batch_size=256)` accepts only integer
batch sizes 1–256. It selects due guardian expiry, institutional expiry and review
timeout rows in registration-ID order, then settles a bounded batch in the
caller's transaction. The CLI samples the server clock once, runs one batch, and
prints only `examined`/`changed` counts. A failed transaction must be investigated;
do not mark partial work complete or add uncontrolled retries.

Choose and monitor a scheduler cadence appropriate to the deployed queue size;
one invocation is not an unbounded backlog drain. Canonical authority reads also
settle due state. Current proof checks reject invalid/expired authority even
before a scheduled sweep, so queue latency is not an authorization extension.
Review timeout stays `PENDING`, clears the deadline, increments the state version,
and writes a unique durable notification row. The owner-scoped notifications GET
exposes only the notification code and state version. **A notification row or GET
result is not proof of email/push delivery**: frontend display or an external
delivery integration must be configured and verified separately. Monitor
outstanding due work, notification consumption and worker failures without
logging personal identifiers.

## Migration, legacy mapping, and identity changes

Application head is `0024_nyay11_authority_state`, following
`0023_nyay22_mentor_ceremony`. It adds seven tables: current authority states,
guardian invitations, institutional email proofs, reviewer assignments, mutation
ledger, aggregate audit events, and durable notifications. Closed-state and proof
shape constraints, uniqueness constraints, and the PostgreSQL append-only audit
trigger accompany the schema. The migration does not manufacture fresh proof
from legacy mutable flags.

| Legacy family | Explicit mappings |
| --- | --- |
| Guardian | `pending` and `sent` → `REQUIRED_PENDING`; `verified` → recorded `VERIFIED`; `rejected` → `REJECTED`; `revoked` → `REVOKED`. Missing row → adult `NOT_REQUIRED` or minor `REQUIRED_PENDING`. |
| Institutional | `pending` → `UNVERIFIED`; `in_review` → `PENDING`; `verified` → recorded `VERIFIED`; `rejected` → `REJECTED`; `expired` → `EXPIRED`; `revoked` → `REVOKED`. Missing row → `UNVERIFIED`. |

Every declared input has an explicit mapping, including the two named guardian
inputs with the same output. Original legacy rows remain. The recorded positive
legacy outcome is then explicitly invalidated with an additional event and a
reproof flag: guardian `VERIFIED` becomes `REQUIRED_PENDING`, institutional
`VERIFIED` becomes `PENDING`. This prevents silent promotion of old flags into the
new proof system. Unknown labels stop the migration instead of being dropped.

The runtime settles age using server civil date and DOB, including eighteenth
birthdays and leap dates. Profile identity edits and dependent proof invalidation
share the profile transaction. DOB and institutional email are the registered
dependencies; unknown dependency fields fail closed. Subsequent edits of a
pending dependency are rejected until reproof. Existing profile mutation keys,
expected-version checks and strict request schemas continue to apply.

**Populated downgrade is deliberately blocked.** If any of the seven new tables
contains a row, `downgrade()` raises `authority_downgrade_requires_empty_graph`,
including when only immutable audit history remains. Do not delete those rows
to force a downgrade. Empty disposable schemas may round-trip; populated release
rollback needs a separately reviewed forward correction or restoration plan.
This change set does not itself run a production migration or authorize a restore.

## Privacy, retention, export, and frontend boundaries

Operational proof/linkage tables are private and subject-scoped. The mutation
ledger encrypts replay outcomes; it does not make invitations or other operational
data public. Authority expiry means unusable proof, **not automatic physical
erasure**. No new statutory retention period is asserted by this feature.

The existing NYAY-19 subject anonymisation/deletion path calls
`erase_owner_authority` inside the owner transaction. It revokes and severs
dependent guardian/reviewer links, removes owned authority states, invitations,
notifications, mutation records, email proofs and reviewer assignments, and
preserves only the separate immutable aggregate audit. The new aggregate audit
column inventory is `id` (event ID, not owner ID), `actor_class`,
`authority_class`, `purpose_code`, `transition_code`, `policy_version`, and
`occurred_at`. There is no user/registration foreign key or free-text detail.
Server-observed proof loss and NYAY-19 dependent erasure are causally attributed
as `PROOF_REVOKED`, actor class `server`, authority class
`server_profile_policy`; they are not falsely attributed to a guardian action or
an owner break-glass command. The internal invalidator accepts no caller-supplied
target state or authority label and affects only non-current proof or linkage
to the exact erased subject. Explicit guardian/owner commands retain their own
actor attribution.
The NYAY-19 configuration and approved operational retention policy remain the
source of erasure scheduling; token/proof lifetimes are not retention approvals.

Owner data export adds `authority_history` only when authority state exists. Its
entry allowlist is `guardian_state`, `institutional_state`, `policy_version`,
`guardian_relationship`, `guardian_consent_version`, `guardian_verified_at`,
`guardian_expires_at`, and `institutional_expires_at`. Internal user/registration
IDs, assignment IDs, raw codes, invitations, keyed hashes, cookies and provider
receipts are not exported. The aggregate audit cannot be relinked through an
owner export index.

Frontend consumers continue to use the canonical server session/profile
projection. Client-written role/status fields, localStorage, sessionStorage and
displayed badges are not authority. An unproven minor stays limited; canonical
401 invalidates private content. Existing screen shells do not gain a student
approval or institutional reviewer self-approval control. This slice is not a
new guardian/reviewer portal, an external identity-verification service, or a
notification transport implementation.

## Validation and release evidence

The accepted RED contract contains 61 state-pair outcomes and 19 structural
contracts. Runtime/API regression tests exercise real command entry points,
provider receipts, replay, loss of proof and privacy projections. The dedicated
native PostgreSQL 16/pgvector producer enforces its exact nonzero inventory,
including migration up/down/up/check on disposable databases, populated legacy
mapping, authorization, concurrency, idempotency, identity changes and immutable
audit behavior. The full repository gate integrates the producer and rejects
missing or fabricated result rows.

Use the exact-head validation summary and sealed evidence manifest for actual
pass counts and runtime versions; this operational document is not a substitute
for a run. A combined rendered-evidence contact sheet must be traceable to the
same sealed matrix. Publication or a green synthetic gate does not authorize
live data migration, grant a legal compliance certification, or release the
separate NYAY-21 history-rewrite HOLD.
