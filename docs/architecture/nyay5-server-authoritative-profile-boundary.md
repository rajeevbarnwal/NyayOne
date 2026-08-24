# NYAY-5 server-authoritative profile boundary

Status: implementation contract for the NYAY-5 frozen commit. Any later
NYAY-18 namespace work must preserve this boundary without modification.

## Authority and ownership

The authenticated server-side session actor is the only profile owner
selector. Profile requests do not accept a user ID, registration ID, profile
ID, actor header, or other client-selected authority in a URL, query, body, or
header. The server resolves exactly one live student registration and exactly
one normalized profile for the session actor. Anonymous, expired, revoked,
deleted, wrong-role, ambiguous, and cross-user requests fail closed before a
profile mutation.

The canonical API is:

- `GET /api/v1/student/profile`
- `PATCH /api/v1/student/profile/personal`
- `PATCH /api/v1/student/profile/academic`
- `PATCH /api/v1/student/profile/interests`
- `POST /api/v1/student/profile/prompt-dismiss`

Mutation queries must be empty and unsafe cookie-authenticated requests require
the trusted-origin policy. The older academic endpoint delegates to this same
service and requires the same explicit profile version; it is not a second
authority.

Registration accepts independently versioned affirmative Terms and Privacy
Notice acknowledgements and returns the same exact four-field HTTP `202`
anti-enumeration projection for new, duplicate, and exact-replay outcomes:
`status=accepted`, `next=otp`, and bounded expiry/resend seconds. Legacy
combined-consent and academic fields remain parseable only to match an exact
sealed v1 idempotency ledger; a new key using that legacy shape is rejected
before any graph is written.

## Canonical projection and persistence

Every successful read and mutation returns one exact projection containing:

- `profile_version` for optimistic concurrency;
- completion version, percent, completed sections, next section, and complete
  state;
- institutional-email verification state;
- guardian requirement and state;
- access mode and disabled capabilities;
- session-scoped prompt state; and
- personal, academic, interests, and goals data.

Legal names and encrypted date of birth remain on the registration identity
row. Academic data remains on the normalized student profile. Interests and
goals are bounded normalized child rows. Prompt dismissal is keyed to the live
authentication session and is removed by session rotation, logout, revocation,
expiry, registration anonymisation, and deletion. No profile authority or PII
is persisted in browser storage.

Completion version `v1` is server-computed as a strict section prefix and can
only be `0`, `34`, `67`, or `100`. It never grants or implies institutional
verification. Personal must complete before academic; personal and academic
must complete before interests. Direct URL or request ordering cannot skip an
incomplete prerequisite.

## Concurrency and uncertain results

Every section write supplies `expected_profile_version`. The server performs a
database compare-and-swap and returns a typed `409 profile_version_conflict`
with the current authorized projection when a stale writer loses. It never
overwrites the winning state.

The frontend navigates or displays success only after a confirmed projection.
For timeouts, aborts, network failures, and ambiguous server failures, it makes
one bounded authoritative read. It treats the write as committed only when
that projection proves the expected version and fields; otherwise it retains
the route and entered values and reports `profile_write_uncertain`.

## DOB, guardian, and restricted capabilities

DOB policy uses one injected request clock and the request's civil date. A
future DOB is rejected with zero mutation. Adult-to-minor and minor-to-adult
changes update DOB, minor state, guardian requirement, access mode, profile
version, and audit evidence atomically. A student cannot create positive
guardian or institutional-verification authority. Changing DOB after verified
institutional identity requires a separately approved step-up ceremony and is
currently denied.

An unverified minor receives `access_mode=limited` with `community` and
`sharing` disabled. Frontend guards prevent those route trees from mounting.
Server-side credential share-projection and verification-token creation also
enforce the persisted guardian state with zero-write denial. Read, revoke, and
delete operations remain available so a limited user can inspect or remove
existing material. There is currently no Community mutation API.

Saving an institutional email does not silently request review. The explicit
`POST /api/v1/auth/student/verification/email/request` endpoint accepts only an
empty body and empty query, derives the address from the authenticated
canonical profile, and records one idempotent, non-authorizing review request.
The internal state becomes `in_review`; the public canonical projection remains
the bounded `pending` state and the endpoint returns that full projection with
HTTP `202`. Repeated requests do not duplicate either the request or its
PII-free audit evidence.

Positive verification remains reviewer-only. A verified row is authoritative
only when its persisted reviewer-issued proof hash matches the canonical saved
institutional-email hash. The projection and login/session claims use this one
shared proof predicate. Migration quarantines legacy positive rows that lack
that proof, and a forged bare `verified` row grants no capability. Unrelated
profile changes retain a valid email-bound proof; changing the saved email
atomically clears it and returns the status to non-authorizing `pending`.

The staff-only `POST /api/v1/auth/student/verification/status` operation is not
an owner-profile API and cannot truthfully calculate the owner's
session-scoped prompt state from a reviewer session. Its exact bounded response
therefore returns the resulting status, the unchanged bound profile version,
and `owner_projection_invalidated: true`. The student client refreshes the full
canonical projection through its own HttpOnly session; no reviewer response is
accepted as an owner projection.

## Browser and session boundary

Protected student routes settle session discovery before `AppShell`, private
components, or private queries mount. The explicit phases are `pending`,
`authenticated`, `anonymous`, and `unavailable`; a transport failure is never
misclassified as anonymous. Generation fencing prevents an older session
response from winning after rotation or teardown.

Route ownership is literal rather than inferred from a screen number. The
public/mixed inventory is S-01–S-06, S-08–S-09, S-20–S-21, S-25–S-29, and
S-88–S-89. The explicit private inventory is S-07, S-10–S-19, S-22–S-24,
S-30–S-35, S-50–S-65, S-82–S-87, and S-90–S-93. Any implemented or future
student route absent from the public inventory defaults to private and cannot
mount before an authenticated student session settles.

Every browser realm that can mount private student UI holds a shared Web Locks
lease named `nyayone.student.auth-session.v1`; each student API request also
holds a shared lease through complete response observation. Login/signup
rotation, logout, and accepted deletion queue one exclusive lease, clear and
quiesce every realm over the identity-free
`nyayone.student.auth-transition.v2` BroadcastChannel, perform the cookie
operation and authoritative session probe under that exclusive lease, publish
the end before releasing it, and reacquire the realm shared lease before any
private rediscovery. Broadcast timing is not authority: a delayed or frozen
realm's shared lease blocks the exclusive operation. Missing Web Locks or
BroadcastChannel support, a failed private-state cleanup, or a peer NACK leaves
private routes unavailable and performs no cookie operation; there is no timer
or storage fallback.

An exact authentication-loss 401 immediately unmounts private UI. At most one
unsaved profile form may cross that boundary in process memory, tagged with the
prior server actor and bounded by a five-minute TTL. It is restored once only
after a fresh server session proves the same actor. A different actor, explicit
logout, deletion, failed discovery, TTL expiry, or realm reload erases it. It
is never written to browser storage, a URL, history, or a deterministic global.

Legacy private `ls-reports-*` and `ls-reminder-prefs-*` entries are snapshotted
and exhausted in batches of at most 256 matching keys. Exact retired keys are
also removed. Cleanup never calls `storage.clear()` and preserves every
unrelated key; an unreadable storage area or failed owned-key removal denies a
cookie transition.

The browser may keep only unsaved form drafts in process memory. It cannot use
Web Storage, Cache Storage, IndexedDB, JavaScript-readable cookies, URLs,
history, service-worker caches, or deterministic globals to manufacture
identity, ownership, session state, profile completion, verification,
guardian state, access mode, or durable profile data. The literal NYAY-2 and
NYAY-19 cleanup and UUID oracles remain authoritative.

For Sprint 1, mentor session completion (M-01) is admin-only. Student routes do
not expose tutor or issuer mutation controls, and browser lawyer state cannot
be promoted into tutor authority. The server-issued lawyer/tutor session and
verified `TutorProfile` ownership ceremony is explicitly deferred to NYAY-22
as a separate security boundary with its own specification, gates, and
independent review. Cookie-backed completion therefore re-locks and revalidates
an active administrator session immediately before the effect. The inherited
header-driven tutor service contract remains available only to the isolated
development/test harness; it is not a shipped tutor authentication ceremony.

## Migration and release boundary

Revision `0021_nyay5_profile_boundary` is the only direct child of the sealed
`0020_auth_retention_lifecycle` revision. Revisions `0001` through `0020`
remain byte-for-byte frozen. The new migration validates its parent data,
exact schema, PostgreSQL table persistence, and absence of RLS, policies,
rewrite rules, and user triggers on its owned tables before committing.
Downgrade is permitted only when it is lossless. Production execution remains
fail closed until a new digest-bound four-role approval contract exists;
isolated execution is limited to explicitly opted-in, marker-named,
loopback-only disposable databases.

## Required freeze evidence

The NYAY-5 frozen commit is valid only when all of the following execute and
pass without newly introduced skips or xfails:

1. service, HTTP, lifecycle, migration, release-guard, and compatibility tests;
2. the PostgreSQL 16 + pgvector gate with exact schema/catalog, ownership,
   concurrency, fixed-clock DOB, prompt lifecycle, access, privacy, cleanup,
   and named-mutant results;
3. the real Chromium mobile/desktop, failure, multi-tab, cross-user,
   accessibility, request-authority, and persistence inventory;
4. literal NYAY-2, NYAY-4, NYAY-17, and NYAY-19 regressions;
5. full backend and frontend tests, typecheck, lint, and production build;
6. migration ledger/immutability, CI policy/workflow, and evidence privacy
   verification; and
7. a clean diff plus exact commit, parent, tree, report, and manifest hashes.
