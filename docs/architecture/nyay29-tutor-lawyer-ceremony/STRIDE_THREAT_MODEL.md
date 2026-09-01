# NYAY-29 tutor/lawyer ceremony — STRIDE threat model

Status: **design and threat model only**. Nothing in this document authorizes
backend, frontend, migration, cookie, route, or storage implementation. Sprint
1 M-01 remains administrator-only. NYAY-22 is the separately approved
implementation handoff and requires its own unit, HTTP, PostgreSQL concurrency,
real-Chromium, privacy, and independent review gates.

This model defines the security posture for a future server-issued mentor
session. Ceremony state, invitation state, identity proof correlation,
TutorProfile ownership, consent, session issuance, rotation, expiry,
revocation, logout, recovery, and deletion are authoritative only on the
server. A browser receives no authority from Web Storage, URLs, logs, evidence,
a raw proof, a session secret, a route, or a JavaScript-readable value. The
only eventual browser authority is a host-only, Secure-in-production,
HttpOnly session cookie issued for an isolated mentor session after the whole
ceremony succeeds. There is no client-side key management.

## Scope, assets, and security invariants

The protected assets are:

| Asset | Sensitivity | Required authority and storage posture |
|---|---|---|
| Invitation and ceremony state | Security metadata | Server-owned PostgreSQL state with a finite lifecycle and bounded expiry; the browser may receive only a non-authorizing projection. |
| External identity proof and provider correlation | Identity evidence | Validate through an allowlisted provider and keep raw proof out of browser state, application logs, audit payloads, and QA evidence. Retain only the minimum server-side verification result allowed by policy. |
| `TutorProfile` ownership | Privilege authority | Derived by the server from the authenticated user and exactly one active `TutorProfile`; never selected by a client-supplied user/profile identifier. |
| Purpose-scoped consent grant | Sensitive authorization | Owner/student decision bound to one mentor engagement, one purpose code, one allowed profile-slice set, a version, and grant/revoke timestamps. |
| Mentor session | Authentication secret and capability | A distinct, narrower session class, time-bounded and purpose-bound, represented at the client only by a host-only HttpOnly cookie. Store only a keyed token digest server-side. |
| Profile-slice projection | Personal data | Constructed afresh on the server from current consent, session purpose, owner state, and the relational authority domain. DOB, unmasked mobile, raw identifiers, and non-consented fields are denied by default. |
| Audit record | Security and accountability record | Immutable PII-free issuance, rotation, revocation, expiry, recovery, deletion, and consent events; reversible references, if legally required, live only in a separately encrypted time-bounded link record subject to cryptographic erasure. |
| Sealed QA evidence | Release evidence | Exact-head, privacy-scanned, aggregate or synthetic, inventory-bound, and incapable of carrying cookies, proofs, actor identifiers, or profile values. |

The future implementation must preserve these invariants:

1. A verified active user identity is necessary but insufficient. Authority
   requires **verified TutorProfile ownership** and an **active TutorProfile**
   belonging to the same authenticated actor. A bare positive Boolean, active
   profile row, lawyer credential, or client assertion is never proof.
2. Lawyer verification alone is not tutor authority. A `lawyer` role or
   verified lawyer credential cannot substitute for the tutor/mentor ceremony.
3. A student or owner context is never promoted into mentor authority. A
   context switch ends the incompatible session, completes an authoritative
   server probe, then requires mentor re-authentication and mints a new,
   isolated mentor session.
4. Every mentor capability is server-derived, least-privilege, purpose-bound,
   authority-domain-bound, consent-bound, and checked on every request. The
   authority domain is the relational graph joining the server-session owner,
   registration/profile, invitation, engagement, and mentor profile; it is not
   a client value and does not claim that a platform tenancy model already
   exists. A successful prior check is not a durable client claim.
5. Every ceremony mutation requires one valid opaque `Idempotency-Key` and a
   trusted exact Origin. Authenticated effects scope idempotency to actor,
   operation, and purpose; pre-authentication effects scope it to the non-
   authorizing bootstrap attempt, operation, and purpose. Same-key/same-payload
   replays the exact bounded outcome while the required lookup binding remains;
   mismatch is a typed PII-safe conflict with no mutation.
6. Invitation, proof, exchange, issuance, rotation, revocation, expiry,
   logout, recovery, deletion, and consent changes are transactionally
   linearized. A losing concurrent request cannot leave partial authority.
7. Every lookup and denial is non-enumerating. Unknown and unauthorized
   resources share the same bounded external projection where status semantics
   permit it.
8. There is zero cross-tenant linkage and zero cross-owner linkage: an
   engagement, consent grant, TutorProfile, student/owner subject, session, and
   audit link must resolve inside one server-derived authority domain or the
   operation fails closed. A future tenancy model requires a forward migration
   adding non-null tenancy keys and composite constraints to every member of
   that graph before tenant-aware operation is enabled.

The server-owned design state is:

- `MentorCeremony`: `pending_invitation` → `challenge_issued` →
  `proof_verified` → `exchanged`, with terminal `expired`, `revoked`, or
  `deleted` outcomes.
- `MentorSession`: the one current generation is `active`. Rotation atomically
  moves its predecessor to terminal `rotated_out` and inserts one `active`
  successor. Other terminal states are `expired`, `revoked`, `logged_out`, and
  `deleted`; `rotated_out` is never accepted as live authority or returned by
  a successful probe.
- `MentorEngagement`: one student/owner subject, one verified mentor
  `TutorProfile`, one authority domain, one purpose code, and one current
  consent scope.

No terminal state can return to a live state. Recovery creates a fresh
ceremony generation; it never reactivates an old cookie or old proof.

## Ceremony operation inventory

The threat model covers all nine planned operations. Their names are design
identifiers, not implemented routes:

| Operation ID | Security effect | Minimum required precondition |
|---|---|---|
| `initiateTutorCeremony` | Create or exactly replay a bounded, non-authorizing mentor ceremony/challenge generation; any matching owner invitation remains server-derived and undisclosed. | Any incompatible student/owner context has ended; strict requested mentor class, purpose, privacy-notice version, trusted Origin, and idempotency. |
| `verifyTutorIdentity` | Bind a provider-validated identity result to the server-held nonce and actor, derive exactly one invitation, mark old generations for mandatory revocation for a recovery attempt, and return only the purpose disclosure plus current consent version. Verification does not itself revoke authority. | Live challenge, same actor, server-selected allowlisted provider result, freshness, issuer/audience/nonce validation, unique protected invitation match. |
| `exchangeTutorCeremony` | Record explicit mentor acceptance of the disclosed purpose/version, consume one verified ceremony, and issue the isolated mentor session. For recovery, revoke old generations previously marked at verification in the same transaction before issuing the successor. | Unconsumed proof, explicit acceptance, unchanged disclosure/consent version, verified active `TutorProfile` ownership, current consent/guardian authority, scope reduction, exclusive cookie transition. |
| `getTutorSession` | Return the bounded session/purpose projection. | Valid mentor cookie and live server row; no client-selected actor, profile, subject, or tenant. |
| `rotateTutorSession` | Atomically make the predecessor terminal `rotated_out` and create one `active` successor. | Live mentor session, trusted Origin, idempotency, unchanged actor/profile/purpose/consent authority. |
| `revokeTutorSession` | Revoke the cookie-derived mentor session for its current purpose; broader owner/administrator engagement revocation belongs to a separately approved owner/admin contract. | Live or terminally replayable mentor-session context, trusted Origin, idempotency, and no arbitrary session selector. |
| `logoutTutorSession` | End the presented mentor session and clear its cookie. | Presented session; terminal response remains safe and idempotent even when already absent. |
| `recoverTutorCeremony` | Start only a generic, non-authorizing pre-authentication attempt after loss. It does not identify an actor or revoke authority at initiation. | Bootstrap binding, trusted Origin, idempotency; same-actor proof marks old actor/profile generations for mandatory revocation, and the later exchange must commit that revocation before issuing a successor. |
| `deleteTutorAuthority` | Revoke all mentor authority and apply configured erasure/anonymisation. | Live mentor session plus a distinct, fresh, action-bound server-proven step-up record and short-lived HttpOnly step-up cookie, trusted Origin, idempotency, lifecycle locks, immutable audit marker. |

Every mutation returns a strict response schema and a typed failure from the
closed failure inventory. Failures contain a code, operation-safe field or
state where applicable, and the fixed public message `Request failed`; they do
not echo request values or distinguish unknown from unauthorized identities.

## Exact positive-authority and coordination predicates

**TutorProfile proof.** `TutorProfile.status=active`, `verified_identity=true`,
or `verified_credentials=true` is never sufficient alone. Positive authority
requires exactly one current `TutorProfileOwnershipProof` whose `user_id` and
`tutor_profile_id` equal the same server-authenticated actor and active profile;
whose provider, assurance class, and policy version are allowlisted for the
requested mentor role; whose protected provider-subject HMAC equals the fresh
server-consumed identity result; whose evidence digest and key version are
valid; and whose `issued_at <= now < expires_at`, `revoked_at IS NULL`, and
`deleted_at IS NULL`. The profile and user must also be active and undeleted.
Missing, duplicate, expired, mismatched, bare-positive, or unverifiable proof
rows collapse to the same generic non-enumerating denial. NYAY-22 must add this
persisted provenance predicate through a reviewed forward migration; it may
not reinterpret an inherited Boolean as reviewer/provider proof.

**Invitation and identity-provider binding.** Invitation creation remains a
separately approved owner-scoped prerequisite. It records one protected mentor
match, authority domain, purpose, scope, consent version, and expiry. A partial
unique constraint permits at most one live invitation per protected mentor
match and purpose during this first design version, so identity verification
can derive exactly one invitation without accepting a browser selector.
Missing, multiple, or cross-authority-domain rows fail closed. Supporting
multiple simultaneous invitations later requires a new server-issued
selection ceremony and threat-model revision; a raw invitation reference is
not an acceptable shortcut.

The identity-provider protocol is an exact non-public adapter boundary. The
server chooses one provider from the requested role/purpose policy, creates a
server-held provider transaction from the bootstrap attempt, and uses a
server-to-server pushed start/backchannel result. The browser may traverse the
provider's authentication surface but receives no NyayOne invitation, nonce,
proof, provider-subject, actor, or transaction token. The provider posts the
signed result to the adapter; the browser returns to a parameter-free generic
same-origin landing page and asks `verifyTutorIdentity` to consume the already
bound result. A client-supplied provider selector is rejected rather than used
to choose assurance.

**Pre-authentication idempotency.** `initiateTutorCeremony` and
`recoverTutorCeremony` first create a random server attempt and set
`nyayone_mentor_bootstrap`, a host-only, Secure, HttpOnly, `SameSite=Strict`,
path-scoped cookie with a maximum age of 900 seconds. It is a non-authorizing
lookup binding: it cannot prove identity, invitation, role, profile, consent,
or session scope and private UI never accepts it. Idempotency is scoped to this
attempt, operation, purpose, key HMAC, and canonical request fingerprint.
Cross-browser reuse of the same raw key cannot share an attempt. If the first
response is lost before the bootstrap cookie is installed, its unbound attempt
expires and a retry creates a fresh generic attempt; it never discovers or
replays another browser's attempt by key alone. Once the cookie is installed,
same-key/same-payload is exact replay and a mismatch is a typed zero-mutation
conflict.

**One global cookie barrier.** All owner/student, mentor-bootstrap,
mentor-ceremony, mentor-session, and mentor-step-up cookie operations use the
existing exact NYAY-5 Web Lock `nyayone.student.auth-session.v1` and identity-
free BroadcastChannel `nyayone.student.auth-transition.v2`. The historical
name is intentionally retained so old and new session classes cannot rotate
concurrently. The only valid order is:

1. every realm capable of private owner/student or mentor UI holds one
   persistent shared lease;
2. every authenticated API request takes an additional per-request shared
   lease through complete response observation;
3. a cookie operation publishes transition-start, unmounts private UI,
   completes memory-only cleanup, collects every ACK, drains requests, and
   releases realm shared leases before it queues one exclusive lease;
4. under the exclusive lease, the server locks the actor's session classes;
   issuance/rotation rejects any live or ambiguous conflicting owner/student-
   versus-mentor class, while a targeted end may retire only its presented
   class; the server performs the one cookie operation and completes a
   canonical authoritative session probe;
5. every realm completes terminal/private teardown and the coordinator
   publishes transition-end before releasing the exclusive lease; and
6. each realm reacquires its persistent shared lease before any private
   rediscovery or request.

Missing Web Locks or BroadcastChannel support, a NACK, failed cleanup, failed
probe, ambiguous response, conflicting session class, or shared-lease
reacquisition failure makes all private classes unavailable and performs no
new cookie issuance. There is no timer, Web Storage, or independent mentor-lock
fallback.

**Minor and guardian boundary.** The NYAY-5 persisted age, guardian, and
access-mode predicates remain authoritative. A minor in `limited` mode or with
missing, pending, expired, revoked, deleted, mismatched, or unverifiable
guardian authority cannot grant or receive mentor sharing. Exchange requires
the current server-proven guardian proof and a distinct purpose/slice-specific
guardian consent version in addition to the student's consent. A DOB transition
to minor, guardian revocation, guardian-consent withdrawal, or owner deletion
locks the same engagement/session graph and wins every verify/exchange/read/
rotation race, revoking all related mentor generations before any further
profile slice is projected. The public denial does not reveal DOB, minor state,
guardian identity, or which predicate failed.

**Lifetime, response, replay, and audit boundary.** The bootstrap and ceremony
absolute lifetime ceiling is 900 seconds. A live mentor session has an
absolute lifetime ceiling of 28,800 seconds and an idle ceiling of 1,800
seconds; a deletion step-up proof/cookie has an absolute ceiling of 300
seconds. Deployments may shorten but never lengthen these ceilings. Production
and staging mutations accept only their configured exact HTTPS Origin. The
only non-HTTPS exception is an explicitly enabled local/test profile whose
allowlist contains the literal loopback Origin `http://127.0.0.1:<port>` or
`http://[::1]:<port>`; `localhost`, suffix, wildcard, forwarded-host, null, and
missing Origins remain denied. All ceremony/session responses, including
errors and terminal replays, set `Cache-Control: private, no-store` and
`Vary: Cookie`.

After a cookie-retiring commit, a same-key/same-payload retry with the still-
present predecessor cookie may resolve its terminal idempotency row, return
the exact bounded prior outcome, and repeat the idempotent cookie clear; the
predecessor remains `rotated_out`, `revoked`, `logged_out`, or `deleted` and
never authorizes. If the cookie clear already applied or no lookup binding is
present, the server returns the generic unavailable projection; the browser
must perform the canonical authoritative probe under the global exclusive
transition and may trust only that probe. A network response, replay body, or
client memory cannot prove which cookie generation is live.

Lifecycle audit events are immutable and PII-free: stable event code,
generation, policy/consent versions, protected non-reversible correlation
digest, server time, and bounded outcome only. Any reversible link needed for
an approved legal/security window lives in a separate envelope-encrypted link
record with its own access policy, retention deadline, and per-subject key.
DPDP erasure destroys that link record and key (cryptographic erasure) while
leaving the truthful, non-linkable event immutable. Neither anonymisation nor
erasure edits history or reactivates authority.

## Session initiation boundary

At the session initiation boundary, the student or owner may previously create
a purpose-scoped invitation/consent record through its own server-authoritative
surface, and the mentor may begin a fresh ceremony after any incompatible
browser context has ended. The browser, mentor, and student cannot create
authority: only the server creates a live ceremony generation and derives any
invitation match after identity settles. Every mutation is replay-safe and
non-enumerating, and a replay or concurrency loser cannot mint an additional
session. This boundary separates an authenticated student/owner request from a
future mentor session; it never converts one into the other.

Threats and controls:

| Threat | Required control | Verification | Residual risk |
|---|---|---|---|
| An attacker initiates for another student, owner, authority domain, or `TutorProfile`. | Derive actor and bootstrap attempt server-side; accept no client owner, user, tenancy, registration, session, invitation, provider, or profile selector. Invitation issuance remains a separately approved owner prerequisite with one protected mentor match and current purpose/guardian consent. | HTTP negative matrix for anonymous, wrong-role, cross-user, cross-owner, provider-selection, and malformed selectors; database zero-write assertions. | A legitimately authorized owner can invite the wrong real-world mentor; confirmation must show a privacy-safe protected match and allow immediate revocation. |
| A duplicate, retry, or concurrent request creates multiple ceremony generations. | Mandatory opaque key scoped to the non-authorizing bootstrap attempt + operation + purpose; canonical request fingerprint; unique database constraint and row locking; exact replay only after the HttpOnly binding is installed. | Two-connection PostgreSQL race with one committed generation and one exact replay; lost-pre-cookie and cross-browser cases create no shared replay; mismatch returns typed `409` with no mutation. | A client can consume rate budget with unique keys; quotas remain necessary. |
| Invitation state is used after expiry, revocation, consent withdrawal, or deletion. | One injected server clock, bounded expiry, terminal-state predicates in the same locked transaction as every effect, and no terminal-state resurrection. | Fixed-clock boundary tests plus revoke/expire/exchange races in both lock orders. | A just-in-time legitimate request may lose to revocation by design; availability yields to revocation safety. |
| Invitation references or challenge values leak. | Return only a bounded, non-secret challenge projection; raw nonce, proof, invitation capability, cookie, and internal identifiers are absent from URLs, Web Storage, logs, evidence, and response bodies. | Browser/storage/history/network audit and planted privacy canaries. | Traffic metadata may reveal that a ceremony occurred; minimize observability labels and retention. |
| An attacker enumerates students or mentors from response differences. | Uniform accepted/denied projections where possible; bounded typed errors; no names, profile status, or ownership detail in denials; rate limits keyed server-side. | Status/body/header/size/timing-envelope matrix for unknown, unauthorized, expired, and revoked cases. | Network timing cannot be perfectly identical; bounded service-level monitoring detects material divergence. |
| A client causes resource exhaustion with initiation or retry floods. | Per-actor, per-subject-hash, per-origin/IP budgets; bounded request body; finite generations; transactional cleanup; no unbounded retry loops. | Rate-limit, maximum-generation, and cleanup tests under concurrency. | Distributed attacks can reduce availability and require operational mitigation. |

No initiation response grants tutor or lawyer capability. The effect ends after
creating or replaying a server-side ceremony record and PII-minimal audit event.

## Identity verification boundary

At the identity verification boundary, an external identity proof is accepted
only from the server-selected provider's non-public backchannel after issuer,
audience, signature, nonce, freshness, and server-held ceremony correlation
checks. The authenticated user must satisfy the persisted current
`TutorProfileOwnershipProof` predicate for exactly one active profile. An unverified,
suspended, retired, ambiguous, or substituted profile is denied with no
mutation; actor substitution and provider substitution cannot become session
authority.

Threats and controls:

| Threat | Required control | Verification | Residual risk |
|---|---|---|---|
| Spoofed provider response or forged identity proof. | The server, never the browser, selects the allowlisted provider/policy; validate signature, issuer, audience, nonce, clock bounds, and one-time server-held transaction through the exact pushed start/backchannel adapter. | Valid/invalid signature, issuer, audience, nonce, stale proof, provider-selector, public-callback-token, and algorithm-confusion vectors. | A compromised approved provider can issue bad attestations; provider governance, monitoring, and rapid disablement remain operational controls. |
| A valid proof for actor A is substituted into actor B's ceremony. | Bind proof result to ceremony generation, authenticated user, provider subject digest, purpose, and nonce; compare the same actor under row lock before effect. | Cross-user and simultaneous-tab substitution tests, both request orders, zero session rows on denial. | Provider account recovery can transfer control; high-risk recovery requires renewed ceremony and audit review. |
| Lawyer identity is treated as tutor authority. | Enforce the explicit rule: lawyer verification alone is not tutor authority. Require the tutor/mentor role decision plus verified active TutorProfile ownership and purpose scope. | Role-composition matrix: lawyer-only, tutor-only-unverified, wrong profile, suspended profile, and valid combined case. | Product may later define lawyer-as-mentor eligibility, but that requires a versioned policy and separate approval. |
| Client-supplied profile ID or positive flag wins over server ownership. | Accept no `TutorProfile` selector and require the exact current proof-provenance predicate: same actor/profile, provider-subject HMAC, assurance/policy, evidence digest/key, validity, and active undeleted rows. | Extra-field/query selectors, forged headers/cookies, Boolean-only rows, expired/revoked proof, and duplicate-profile fixtures fail closed. | Ambiguous legacy data blocks legitimate access until repaired. |
| Raw proof or identity data enters retention, audit, or evidence surfaces. | Reduce proof immediately to provider, protected subject digest, verification class, issued/expiry timestamps, and policy version; isolate access; omit raw proof and unnecessary PII everywhere else. | Database column inventory, log/evidence scanner, exception mutation, retention teardown proof. | The minimal attestation remains sensitive correlation data and needs access control and a configured retention window. |
| Verification endpoint becomes a denial-of-service amplifier. | One bounded provider call or backchannel exchange per server generation, circuit breaker, budget, deadline, and no automatic recursive retry. | Provider timeout/error/load matrix with no partial mutation and bounded worker occupancy. | Provider outage blocks new mentor sessions; existing sessions follow separately approved expiry/revocation policy. |

Successful verification establishes a server-side fact only. It does not set a
session cookie and cannot mount mentor UI before exchange and an authoritative
session probe succeed.

## Privilege escalation boundary

At the privilege escalation boundary, every capability is server-derived from
the live mentor session, active consent, purpose, relational authority domain,
guardian authority when applicable, and verified profile.
The student, lawyer, and tutor roles are distinct inputs; none is promoted in
place. Least privilege means a mentor receives only the named operation set and
minimum profile slice required for that purpose, never general owner authority.

Required authorization model:

- The session class is `mentor`, distinct from `student`, `owner`, `lawyer`,
  `admin`, and inherited development/test header actors.
- The session carries server-side references to one actor, one active
  `TutorProfile`, one authority domain, one engagement, one purpose-policy version, one
  consent version, one scope allowlist, issued/last-seen/absolute-expiry times,
  a generation, and a status. The cookie carries only an opaque secret.
- The server recalculates effective scope on every request. Current student and
  guardian consent where applicable, profile proof/status, purpose policy,
  engagement state, session state, and every relation in the authority domain
  must all remain live.
- DOB, unmasked mobile, raw user/profile/registration identifiers, enrollment
  identifiers, and unrelated profile fields are absent unless an explicitly
  versioned per-purpose policy and owner consent allow a particular field.
- Consent withdrawal, profile suspension, owner deletion, engagement
  revocation, administrator revocation, session expiry, or logout linearizes
  before subsequent reads. Cached client state is immediately non-authoritative.
- Every cookie mutation uses the one exact global NYAY-5 lock/channel and the
  six-step order defined above; the server independently rejects conflicting
  session classes. There is no mentor-only lock, and unsupported locks fail
  closed.
- Session issuance is capped at 28,800 seconds absolute and 1,800 seconds idle.
  Rotation makes the predecessor terminal `rotated_out` and one successor
  `active`; recovery verification can only mark old generations after same-
  actor proof has settled, and exchange atomically commits their revocation
  before issuing a successor.

Threats include confused deputy use of an owner cookie, cross-purpose scope
reuse, consent-version rollback, stale session generation, forged role claims,
and cross-owner or future-tenancy engagement substitution. Controls are exact session-class
dependencies, origin validation, composite ownership predicates, scope
intersection, generation fencing, transactional lifecycle locking, and
non-enumerating denial. Verification requires unit authorization matrices,
HTTP schema and origin tests, native PostgreSQL concurrency races,
real-Chromium multi-tab/session tests, privacy scans, and independent review.
Residual risk is bounded but not eliminated: an authorized mentor can observe
the minimum disclosed data during a live purpose. Product must present that
disclosure before consent, and revocation cannot erase information already
legitimately perceived.

## STRIDE coverage matrix

This STRIDE coverage matrix records each threat, protected asset, required
control, verification method, owner, and residual risk across every trust
boundary. Control owners are `Identity`, `Mentor Platform`, `Data/Privacy`, or
`Release Engineering`; they are accountable roles, not evidence that a control
has already been implemented.

| Boundary | STRIDE category | Threat and asset | Required control | Verification and control owner | Residual risk |
|---|---|---|---|---|---|
| TB-01 Student/owner ↔ platform | Spoofing | Forged owner session initiates or revokes an engagement. | Server-resolved host-only HttpOnly session, active-row/role check, exact trusted Origin, protected mentor match, no client actor/invitation/provider selector. | Anonymous/invalid/revoked/wrong-role/provider-selection HTTP matrix; Identity. | Stolen live owner device remains possible until expiry/revocation. |
| TB-01 Student/owner ↔ platform | Tampering | Purpose, subject, consent scope, or idempotency payload is altered. | Strict schema, server-derived subject, canonical fingerprint, actor+operation+purpose idempotency, signed server policy version. | Extra-field and payload-mismatch tests with database zero-write; Mentor Platform. | A legitimate owner can choose an unintended allowed purpose. |
| TB-01 Student/owner ↔ platform | Repudiation | Owner disputes invitation, consent, or revocation. | Append-only PII-minimal event with action code, protected actor/engagement references, policy/consent version, server timestamp, and request correlation digest. | Audit immutability and event-completeness tests; Data/Privacy. | Audit proves platform observation, not the human's subjective intent. |
| TB-01 Student/owner ↔ platform | Information disclosure | Responses reveal mentor/student existence or excess profile data. | Non-enumerating bounded responses, purpose disclosure preview, no identifiers, `Cache-Control: private, no-store` and `Vary: Cookie`. | Unknown-versus-unauthorized matrix and privacy canaries; Data/Privacy. | Timing and traffic volume metadata remain. |
| TB-01 Student/owner ↔ platform | Denial of service | Initiation, consent toggling, or revocation flood exhausts resources. | Rate budgets, body bounds, finite generations, transactional dedupe, prioritized revocation path. | CPU-pressure and PostgreSQL contention tests; Mentor Platform. | Distributed abuse can reduce availability. |
| TB-01 Student/owner ↔ platform | Elevation of privilege | Owner/student cookie is accepted as mentor authority. | Exact session-class dependency and explicit end/probe/re-authenticate/new-session sequence; never in-place promotion. | Persona-switch and cookie-confusion tests; Identity. | Misconfigured future route dependencies remain a review risk. |
| TB-02 Mentor ↔ platform | Spoofing | Attacker presents another mentor's session or proof. | Keyed cookie digest, same-actor backchannel proof binding, exact current `TutorProfileOwnershipProof`, generation and expiry checks. | Cross-user cookie/proof, bare-Boolean, and provider-selector substitution tests; Identity. | Compromised mentor endpoint persists until revocation. |
| TB-02 Mentor ↔ platform | Tampering | Mentor changes purpose, engagement, scope, profile, authority-domain, or provider selectors. | Those values are server-owned and absent from mutable request fields; strict schema rejects extras. | Schema fuzzing and server-state comparison; Mentor Platform. | A server policy defect could over-project data. |
| TB-02 Mentor ↔ platform | Repudiation | Mentor disputes verification, exchange, access, rotation, or logout. | Append-only bounded events with server actor/profile/engagement references and generation transitions; no raw proof. | Event inventory and append-only database test; Data/Privacy. | Shared physical devices complicate human attribution. |
| TB-02 Mentor ↔ platform | Information disclosure | Mentor reads fields beyond consent or another owner/authority domain. | Per-request intersection of session scope, purpose policy, current student/guardian consent, owner state, and relational authority domain; deny-by-default serializer. | Seeded forbidden fields and two-owner/cross-domain projection matrix; Data/Privacy. | Authorized screen observation cannot be technically recalled. |
| TB-02 Mentor ↔ platform | Denial of service | Proof, rotation, or recovery churn locks rows or provider resources. | Per-operation budgets, one-flight generation locks, bounded provider deadline, no recursive retries. | Parallel-request and provider-failure tests; Mentor Platform. | Provider outage blocks new sessions. |
| TB-02 Mentor ↔ platform | Elevation of privilege | Lawyer-only, stale, suspended, or unverified actor gains tutor scope. | Role-policy version plus verified active `TutorProfile` ownership; least-privilege scope and current status recheck. | Full role/profile state composition matrix; Identity. | Erroneous reviewer verification remains a governance risk. |
| TB-03 Mentor ↔ student engagement | Spoofing | A mentor substitutes a different engagement or student. | Server-derived engagement from session; complete actor/profile/invitation/subject authority-domain relation; no raw subject selector. | Cross-engagement, cross-owner, and corrupt-domain negative tests; Mentor Platform. | A wrongly linked server record must fail data-integrity validation. |
| TB-03 Mentor ↔ student engagement | Tampering | Consent version or purpose scope is rolled back to regain data. | Monotonic consent version, row locks, current-policy intersection, terminal grant history. | Concurrent grant/revoke and stale-version tests; Data/Privacy. | Races intentionally favor restriction and may interrupt legitimate work. |
| TB-03 Mentor ↔ student engagement | Repudiation | Either party disputes consent withdrawal or access termination. | Append-only grant/revoke/termination events with policy version and server time; expose a bounded history to the owner. | Audit sequence and privacy projection tests; Data/Privacy. | Records cannot prove comprehension of disclosure text. |
| TB-03 Mentor ↔ student engagement | Information disclosure | Direct peer channel exposes DOB, mobile, raw IDs, or unrelated profile slices. | Platform-mediated allowlisted projection only; no direct database/client store sharing; explicit per-purpose student and, for a minor, current guardian consent. | Field-level canaries across UI, API, export, log, and evidence; Data/Privacy. | Participants can manually disclose information outside the platform. |
| TB-03 Mentor ↔ student engagement | Denial of service | One party repeatedly revokes/re-invites or floods active-session actions. | Finite state graph, cooldown/rate budget, idempotent terminal operations, owner-prioritized revoke. | State-machine and rate-limit tests; Mentor Platform. | Abuse may require moderation outside this ceremony. |
| TB-03 Mentor ↔ student engagement | Elevation of privilege | An allowed tutoring purpose is reused for legal, community, or owner actions. | Closed purpose-to-capability and purpose-to-field policy; no wildcard scopes; audience check on every route. | Purpose-confusion and route inventory tests; Mentor Platform. | New purposes require explicit threat-model and contract revision. |
| TB-04 External identity provider ↔ platform | Spoofing | Forged provider, signature, issuer, audience, subject, or callback. | Server-selected allowlisted provider/key/algorithm, TLS, signature and issuer/audience validation, non-public pushed start/backchannel; no frontend token. | Protocol corpus, client-provider-selector, public-callback-token, and fake-provider tests; Identity. | Approved provider compromise remains systemic residual risk. |
| TB-04 External identity provider ↔ platform | Tampering | Authorization response, nonce, timestamp, or proof class is modified/replayed. | Server-held nonce and ceremony binding, short expiry, single consumption, canonical provider response validation. | Replay, stale, duplicate, altered-nonce, and concurrent callbacks; Identity. | Clock synchronization failure can deny legitimate proof. |
| TB-04 External identity provider ↔ platform | Repudiation | Provider or operator disputes the verification result. | Retain minimal signed-result digest, provider/policy version, validation outcome, and time; never raw proof in ordinary audit. | Digest verification and evidence-minimization review; Identity. | Provider audit availability is external. |
| TB-04 External identity provider ↔ platform | Information disclosure | Excess owner or mentor PII is sent to provider or leaked in callback/referrer. | Data-minimal request, exact redirect/callback policy, no owner profile data, no proof/token in application URLs/logs, no third-party resources on callback. | Network/referrer/log scan and provider-request schema test; Data/Privacy. | Provider necessarily observes its own subject and event metadata. |
| TB-04 External identity provider ↔ platform | Denial of service | Provider latency or outage consumes workers and blocks ceremony. | Deadline, circuit breaker, bounded retries outside request, no partial mutation, clear non-authorizing unavailable state. | Timeout, disconnect, retry-budget, and recovery tests; Mentor Platform. | New session availability depends on provider health. |
| TB-04 External identity provider ↔ platform | Elevation of privilege | A weaker proof type or lawyer proof is mapped to tutor authority. | Closed proof-policy map per role/purpose, minimum assurance, active TutorProfile ownership after proof, explicit lawyer-is-not-tutor rule. | Downgrade and proof-class substitution matrix; Identity. | Policy configuration error requires independent review. |
| TB-05 API/service ↔ PostgreSQL | Spoofing | Service connects to the wrong database/schema/role or resolves a forged row. | Trusted runtime configuration, explicit schema, expected role, ownership predicates, migration/catalog checks. | PG16/pgvector environment and catalog authority gates; Data/Privacy. | Compromised database credentials remain severe. |
| TB-05 API/service ↔ PostgreSQL | Tampering | Direct or concurrent writes bypass lifecycle, idempotency, consent, or audit. | Constraints, foreign keys, unique indexes, row/advisory locks, optimistic versions, one transaction, append-only audit enforcement. | Native PostgreSQL concurrency and catalog mutant suite; Mentor Platform. | Privileged DBA action is an operational trust. |
| TB-05 API/service ↔ PostgreSQL | Repudiation | Mutation commits without a corresponding lifecycle/audit event. | Mutation and event in the same transaction; postcondition verifies exact event inventory. | Injected commit failures and event-count assertions; Data/Privacy. | Database-level disaster recovery may require evidence reconciliation. |
| TB-05 API/service ↔ PostgreSQL | Information disclosure | Raw cookie, idempotency key, proof, DOB/mobile, or identifiers persist in unintended columns. | Keyed digests/ciphertext where approved, closed column inventory, minimum projection, PII-free immutable events, separately encrypted link records with cryptographic erasure, configured retention. | Schema introspection, row scan, privacy export, key-destruction, and teardown tests; Data/Privacy. | Encrypted sensitive data remains sensitive until its link key is destroyed. |
| TB-05 API/service ↔ PostgreSQL | Denial of service | Lock amplification, unbounded rows, or cleanup contention blocks auth/revoke. | Fixed lock order, bounded statement/lock timeouts, indexed predicates, finite generations, non-overlapping retention worker. | Lock-order races and production-size sanitized rehearsal; Mentor Platform. | Safety-first lock failure may deny availability. |
| TB-05 API/service ↔ PostgreSQL | Elevation of privilege | Cross-owner/authority-domain linkage or stale positive state authorizes access. | Complete relational owner/invitation/engagement/profile proof predicates, current student/guardian consent and session generation, fail-closed ambiguity; future tenancy requires forward-migrated non-null composite keys. | Cross-owner/domain canaries and intentionally corrupt graph fixtures; Mentor Platform. | Legacy corrupt data blocks access until repaired. |
| TB-06 Runtime ↔ audit/CI/evidence | Spoofing | Evidence from another repository, head, run, or environment is accepted. | Exact-head provenance, remote-head readback, SHA-256 manifest, closed inventory, HEAD_CHANGED invalidation. | NYAY-14 validator with seeded malformed packages; Release Engineering. | A compromised build host can still fabricate inputs and requires organizational controls. |
| TB-06 Runtime ↔ audit/CI/evidence | Tampering | Logs, reports, contact sheet, or manifests are altered or omitted. | Immutable archive, exact inventory equality, digest readback, zero-executed cannot pass, sealed visual overview traceability. | Manifest mutants and clean-archive verification; Release Engineering. | Hash publication channel integrity remains an operational dependency. |
| TB-06 Runtime ↔ audit/CI/evidence | Repudiation | Reviewer or release operator disputes what was tested or approved. | Named reviewed head, command/runtime inventory, limitations, verdict, attachment IDs, and append-only Jira record. | Independent readback and evidence reconciliation; Release Engineering. | Human account compromise is outside artifact cryptography. |
| TB-06 Runtime ↔ audit/CI/evidence | Information disclosure | Cookies, OTPs, session secrets, raw proof, actor IDs, PII, URLs with secrets, or database endpoints enter artifacts. | Synthetic fixtures, diagnostic allowlist, pre-seal privacy scanner with planted canary, restricted raw logs, aggregate contact sheet. | Credential/PII scanners and adversarial seeded values; Data/Privacy. | Novel secret formats can evade pattern-only detection, so source review remains required. |
| TB-06 Runtime ↔ audit/CI/evidence | Denial of service | Huge or adversarial evidence prevents validation or upload. | Size/file-count/depth bounds, regular-file/no-link rules, streaming hashes, timeout with `BLOCKED`, no partial PASS. | Oversize, archive-bomb, symlink, and missing-file mutants; Release Engineering. | A bounded audit can still be delayed by infrastructure outage. |
| TB-06 Runtime ↔ audit/CI/evidence | Elevation of privilege | A PASS verdict or development header actor becomes production authority. | Evidence is never runtime input; production rejects header actors; merge controls require exact checks/approvals; no test bypass ships. | Production-mode header tests, source contract, and merge-rule readback; Release Engineering. | Ruleset administrator action requires audited owner governance. |

The public typed failure inventory is closed and generic:

| HTTP status | Stable public code | Collapsed internal reasons | Mutation rule |
|---|---|---|---|
| `400` | `INVALID_REQUEST` | malformed or unsupported request shape | none |
| `400` | `INVALID_IDEMPOTENCY_KEY` | absent or invalid mutation idempotency key | none |
| `400` | `ORIGIN_REJECTED` | absent, malformed, or untrusted mutation Origin | none |
| `401` | `AUTHENTICATION_REQUIRED` | no live cookie-derived session for the requested operation | none; clear an invalid cookie under the global barrier |
| `403` | `AUTHORIZATION_DENIED` | wrong role; unverified/current-proof failure; cross-user, cross-owner, cross-domain, provider-selection, invitation ambiguity; guardian/consent absent or changed; forbidden purpose | none; all sensitive reasons collapse to this single public code |
| `403` | `STEP_UP_REQUIRED` | the separately action-bound deletion step-up has not been established | none |
| `404` | `RESOURCE_UNAVAILABLE` | missing, mismatched, ambiguous, or inaccessible protected resource | none |
| `409` | `IDEMPOTENCY_CONFLICT` | same key with a different canonical fingerprint | none |
| `409` | `CONCURRENT_STATE_CHANGED` | a concurrent terminal or authority transition won | none |
| `409` | `CEREMONY_REPLAYED` | a consumed ceremony is replayed without the exact sealed outcome binding | none |
| `409` | `SESSION_CONFLICT` | live or ambiguous owner/student-versus-mentor class | none and no cookie issuance |
| `409` | `SESSION_STALE` | stale session generation or state observation | none |
| `410` | `SESSION_EXPIRED` | server-clock session expiry | terminalize and retire only the presented session cookie |
| `410` | `AUTHORITY_TERMINAL` | ceremony or authority expired, revoked, deleted, or otherwise terminal | none beyond materializing the terminal state once |
| `410` | `STEP_UP_EXPIRED` | server-clock expiry of the action-bound deletion step-up | retire only the step-up cookie |
| `429` | `RATE_LIMITED` | bounded actor/attempt/origin budget exceeded | none |
| `503` | `PROVIDER_UNAVAILABLE` | server-selected provider deadline, circuit, or backchannel failure | none |

Every response has the fixed message `Request failed`, strict schema, PII-safe
headers/body, `Cache-Control: private, no-store`, and `Vary: Cookie`. Internal
reason codes may be recorded only as bounded PII-free audit codes and never
returned. Unknown, unauthorized, missing, mismatched, ambiguous, and cross-
domain resources are indistinguishable within their public status/code class.

Release posture remains fail closed. Structural design completeness does not
prove a control is implemented. NYAY-22 needs separate approval, an explicit
implementation handoff, threat-model reconciliation against the implemented
schema and code, and all named QA gates before M-01 or any mentor route can use
this ceremony.
