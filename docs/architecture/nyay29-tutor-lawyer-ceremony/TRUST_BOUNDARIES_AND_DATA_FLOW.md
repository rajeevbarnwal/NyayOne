# NYAY-29 tutor/lawyer ceremony — trust boundaries and data flow

Status: **design-only authority map**. This document defines a future ceremony
boundary; it does not implement or authorize mentor authentication. M-01 stays
administrator-only. NYAY-22 requires separate approval before implementation.

The architectural rule is server authority: the server and PostgreSQL hold the
only authoritative invitation, identity-verification, TutorProfile ownership,
consent, engagement, session, revocation, expiry, recovery, and deletion state.
A browser stores no such state in localStorage, sessionStorage, IndexedDB,
CacheStorage, service-worker caches, JavaScript globals, route/history state,
or readable cookies. The future mentor credential is an opaque host-only
HttpOnly cookie; the server stores only its keyed digest and lifecycle row.

## Actors and authoritative state

The actors are student, owner, guardian, lawyer, tutor, mentor, administrator,
identity provider, retention worker, and independent reviewer. The server, not
any actor's browser, resolves identity, role, ownership, the relational
authority domain, purpose, consent, scope, and lifecycle state. An
administrator may review or revoke according to policy but cannot turn an
arbitrary lawyer or tutor browser assertion into a mentor session.

| Actor or component | May request | Cannot assert or select | Authoritative source |
|---|---|---|---|
| Student/owner | Through a separately approved owner surface, create or revoke a purpose-scoped invitation, grant/withdraw an explicit profile-slice consent, and view bounded engagement state. | Raw mentor selector, owner/subject ID, tenancy, active `TutorProfile`, mentor capability, session state, or successful verification. | Existing server-issued owner/student session plus the current relational owner graph. |
| Guardian | Grant or withdraw a separately versioned purpose/slice consent when current server-proven guardian authority permits it. | Student DOB/state, guardian linkage, mentor identity, or consent authority from a browser assertion. | NYAY-5 persisted guardian proof, current access mode, and server session; revocation wins every sharing race. |
| Lawyer | Begin identity verification if a future purpose policy permits it. | Tutor role, active TutorProfile ownership, mentor session, student scope, or owner authority. Lawyer verification alone is not tutor authority. | Existing verified identity plus the new ceremony's server checks. |
| Tutor/mentor | Accept the disclosed purpose/version, complete identity proof, exchange a verified ceremony, use only the purpose-bound scope, rotate/logout/recover/delete own authority. | Another actor/profile/engagement/authority domain, provider, invitation, consent scope, expiry, or role by request field/header. | Same authenticated actor resolved to exactly one active `TutorProfile` with one current persisted `TutorProfileOwnershipProof`. |
| Administrator | Apply explicitly approved review/revocation operations and investigate bounded audit events. | Impersonation through client headers, silent consent, or unbounded profile access. | Separate active administrator session and policy-controlled service operation. |
| External identity provider | Return a signed, bounded identity result through the non-public pushed start/backchannel adapter correlated to a server-held transaction. | NyayOne role, TutorProfile ownership, purpose, consent, authority domain, or session capability. | Server-selected provider key/issuer plus NyayOne's validation and mapping policy; no frontend token. |
| Ceremony/session API | Validate, reduce scope, transact lifecycle changes, project bounded responses. | Trust any client copy of state or a prior successful response. | Current locked PostgreSQL rows and one injected server clock. |
| PostgreSQL | Persist the finite graph and append-only audit evidence. | Define product authorization without service-level purpose/scope checks. | Reviewed schema, constraints, indexes, migrations, and service transaction. |
| Retention worker | Apply configured expiry, anonymisation, or deletion and aggregate reporting. | Invent retention periods, reactivate terminal state, or expose row values. | NYAY-19 configuration and locked lifecycle predicates. |
| CI/evidence tooling and reviewer | Test exact-head contracts with synthetic fixtures and sealed artifacts. | Become authentication authority, handle production secrets, or certify zero-executed gates. | Repository contract, raw gate outputs, manifest, and independent readback. |

The authoritative entity graph is closed:

| Entity | Required server-owned bindings | Lifecycle |
|---|---|---|
| `MentorBootstrapAttempt` | Random attempt digest, browser-binding digest, requested role/purpose, key HMAC, canonical fingerprint, timestamps; no actor, invitation, profile, consent, or authority. | Non-authorizing; absolute expiry at or before 900 seconds; terminal consumed/expired. |
| `MentorInvitation` | Relational authority domain, student/owner subject, exactly one protected mentor match, purpose-policy version, requested disclosure scope, initiator session actor, idempotency record. A partial unique constraint permits at most one live invitation for the protected mentor match + purpose in this design. | `pending` → `accepted`; terminal `expired`, `revoked`, `deleted`. Invitation creation remains a separately approved owner prerequisite. |
| `MentorCeremony` | Bootstrap attempt, server-held nonce/challenge digest, server-selected provider/policy, generation, and timestamps; only after backchannel proof may the server bind the verified mentor actor, protected proof-result digest, and exactly one derived invitation. | `pending_invitation` → `challenge_issued` → `proof_verified` → `exchanged`; terminal `expired`, `revoked`, `deleted`. Maximum absolute lifetime 900 seconds. |
| `TutorProfileOwnershipProof` | Same user/profile, allowlisted provider + assurance + policy version, protected provider-subject HMAC, evidence digest/key version, issued/expiry/revoked/deleted timestamps. | Current only while `issued_at <= now < expires_at`, not revoked/deleted, and the same user/profile remain active; bare positive flags never satisfy it. |
| `MentorEngagement` | Exactly one relational authority domain joining one student/owner subject, one verified mentor TutorProfile, one protected invitation, one purpose, and current consent grants. | `pending` → `active`; terminal `expired`, `revoked`, `deleted`. |
| `PurposeConsentGrant` | Engagement, disclosure purpose, exact allowed profile fields/capabilities, disclosure-text/policy version, version, grant/revoke timestamps and actors; a minor also needs a distinct guardian grant/proof. | `active` or terminal `revoked`/`expired`; a new grant is a new version, never mutation back to active. |
| `MentorSession` | Engagement, mentor actor, TutorProfile, authority domain, purpose, student/guardian consent versions, scope snapshot ceiling, token digest, generation, issued/last-seen/absolute-expiry times. | One current `active`; rotation atomically makes its predecessor terminal `rotated_out` and one successor `active`; other terminal states are `expired`, `revoked`, `logged_out`, `deleted`. Absolute ceiling 28,800 seconds; idle ceiling 1,800 seconds. |
| `MentorAuthorityStepUp` | Live mentor actor/session, exact delete action/fingerprint, server proof result, one-time digest, issued/expiry/consumed timestamps. | Non-transferable, HttpOnly-bound, consumed once, absolute ceiling 300 seconds. |
| `MentorLifecycleAudit` | Stable event code, generation, purpose/policy/consent versions, protected non-reversible correlation digest, server time, bounded outcome; no PII or secrets. | Immutable and append-only. It is never edited or deleted as a lifecycle shortcut. |
| `MentorAuditLink` | Separately envelope-encrypted reversible actor/engagement linkage, retention deadline, key version, access purpose. | Access-controlled and time-bounded; DPDP erasure destroys the link row and per-subject key, leaving the audit event non-linkable. |

The `scope snapshot ceiling` is not a permanent grant. On every mentor request,
the server intersects it with current purpose policy, current student consent,
current guardian authority/consent where applicable, current engagement,
current persisted profile-ownership proof, every relation in the authority
domain, and live session state. Any missing or narrower input wins and may
cause immediate denial or linearized revocation.

The **authority domain** is a server-derived relational graph, not a client
value and not a claim that the current platform already implements tenancy. It
joins the session actor, owner/registration/profile, protected invitation,
engagement, mentor profile/proof, and consent records. Every edge must resolve
to exactly one active expected owner relation. Missing, duplicate, or cross-
owner edges fail closed. This gives zero cross-owner and zero cross-tenant
linkage now. If tenancy is introduced later, a forward migration must add
non-null tenancy keys and composite constraints to every graph member before
tenant-aware operation is enabled.

## Trust-boundary inventory

The trust boundary inventory covers browser, API, external verification,
PostgreSQL, audit, and evidence surfaces. Each crossing is deny-by-default,
typed, non-enumerating, and data-minimal; no crossing trusts a client-selected
actor, profile, subject, tenancy/domain, provider, invitation, purpose,
consent, or session state.

| ID | Boundary | Data allowed to cross toward the platform | Data allowed to cross outward | Mandatory controls |
|---|---|---|---|---|
| TB-01 | Student/owner browser ↔ separately approved owner-engagement API | Strict invitation/consent intent: purpose code, allowlisted fields, expected version, opaque idempotency key; ambient owner/student HttpOnly cookie and exact trusted Origin. This prerequisite remains separately approved and outside the nine-operation mentor-auth contract. | Accepted/denied bounded state, expiry/cooldown, disclosure and current version; no raw subject/mentor identifier, invitation capability, mentor cookie, URL token, or transfer secret. | Server-derived owner/domain and protected unique mentor match, strict schemas, rate limits, student plus current guardian consent where applicable, global cookie barrier, private/no-store + `Vary: Cookie`, non-enumerating denial. |
| TB-02 | Mentor browser ↔ auth/ceremony API | Strict acceptance/proof/lifecycle intent, opaque idempotency key, exact Origin; ambient non-authorizing bootstrap or ceremony binding, mentor session, or fresh action-bound step-up HttpOnly cookie. | Non-authorizing next-step projection; verification returns only purpose disclosure + current consent version; exchange/session probe returns bounded session projection; no nonce, raw proof, provider/transaction token, invitation, session secret, owner ID, or hidden profile state. | Same actor; exact current `TutorProfileOwnershipProof`; explicit mentor acceptance; current student/guardian consent; exact lifetimes; one global fail-closed cookie barrier; server rejects conflicting session classes. |
| TB-03 | Mentor session ↔ student/owner engagement | Server request context only: mentor actor/profile/proof, live session generation, purpose, authority domain, current engagement and student/guardian consent versions. There is no direct browser-to-browser authority channel. | A server-rendered allowlist of the minimum fields/actions for that purpose. | Complete relational domain, current consent intersection, limited-minor sharing denial, no wildcard scopes, zero cross-owner/cross-tenant linkage, PII-free disclosure-class audit. |
| TB-04 | External identity provider ↔ verification service | A server-to-server pushed start created from a server-selected provider/policy and a server-held transaction; minimum protocol data over TLS, no owner/student profile data. The browser receives no NyayOne token. | Signed/bound backchannel identity result to the non-public adapter; browser returns only to a parameter-free generic same-origin landing page. | Allowlisted issuer/key/algorithm, audience/signature/nonce/freshness, one-time correlation, provider-selection denial, no public token callback, bounded deadline, raw proof isolation and retention. |
| TB-05 | API/service ↔ PostgreSQL | Parameterized, server-derived actor/profile/proof/engagement/session/domain IDs and canonical fingerprints inside one transaction. | Only rows necessary for the current effect/projection. | Explicit schema/role, complete relational predicates, constraints/indexes, fixed lock order, unique idempotency scope, row/advisory locks, encrypted/keyed values, immutable PII-free audit + separately encrypted link, configured retention/cryptographic erasure. |
| TB-06 | Runtime ↔ audit/telemetry/CI/evidence | Stable event/stage/error codes and aggregate counts. | Privacy-safe operational metrics and sealed synthetic exact-head evidence. | No raw request/body/proof/cookie/OTP/token/idempotency key/profile value; redaction before emission; planted canaries; closed manifest; exact-head and attachment readback. |

Crossing any boundary never changes authority merely because transport
succeeded. Only a committed server transaction and subsequent authoritative
read can prove a new state. Network aborts and ambiguous responses remain
uncertain until a bounded authoritative probe; they are never treated as
success from local state.

The mentor session cookie is a distinct server-side session class. It is
host-only (no `Domain`), HttpOnly, Secure outside explicit local/test,
`Path=/`, and `SameSite=Lax`, consistent with NYAY-4/NYAY-8. It contains an
opaque CSPRNG secret only; no actor, role, profile, domain, purpose, consent, or
expiry claims. `nyayone_mentor_bootstrap`, `nyayone_mentor_ceremony`,
`nyayone_mentor_session`, and `nyayone_mentor_authority_step_up` are the
planned cookie names; the bootstrap is a non-authorizing pre-authentication
idempotency binding, not a session. All responses, including errors, use
`Cache-Control: private, no-store` and `Vary: Cookie`.

There is exactly one cookie-coordination protocol for owner/student and every
mentor cookie class. It uses the existing NYAY-5 Web Lock
`nyayone.student.auth-session.v1` and identity-free BroadcastChannel
`nyayone.student.auth-transition.v2`; no mentor-specific lock exists. The
mandatory order is: persistent realm shared lease; per-request shared lease
through full response observation; transition-start, private unmount,
memory-only cleanup, all ACKs, request drain, and shared-lease release; one
exclusive cookie operation plus a canonical authoritative probe while the
server locks actor session classes; issuance/rotation rejects a live or
ambiguous conflicting owner/student-versus-mentor class, while a targeted end
may retire only its presented class; terminal/private teardown and transition-
end before exclusive release; then persistent shared reacquisition before any
private rediscovery or request. Missing Web Locks/BroadcastChannel, NACK,
cleanup/probe failure, ambiguous result, conflict, or reacquisition failure
blocks every private class. There is no timer or storage fallback.

Production/staging mutations accept only the configured exact HTTPS Origin.
An explicitly enabled local/test profile may allow only literal
`http://127.0.0.1:<port>` or `http://[::1]:<port>` Origins. It never accepts
`localhost`, wildcard/suffix, forwarded-host, null, or missing Origin.

## Student or owner to mentor handoff

The student or owner to mentor handoff is not an authority transfer. When a
single browser changes persona, it must end the existing incompatible context,
complete an authoritative probe, re-authenticate the mentor, and receive a new session
only after same actor verification against the current persisted TutorProfile ownership
proof predicate. The
server and client fail closed if any end, cleanup, proof, ownership, consent,
or probe step is uncertain.

Two cases are distinguished:

1. **Separate-device invitation.** The student/owner's authenticated context
   creates the server invitation and purpose consent, then remains an owner
   context. The mentor authenticates independently on another browser. No
   owner cookie or authority crosses devices.
2. **Same-browser persona switch.** The realm executes the exact global NYAY-5
   lease order: persistent and per-request shared leases settle; transition-
   start, unmount, cleanup, ACK/drain and shared release precede one exclusive
   owner-session end and canonical probe; teardown/end precede exclusive
   release; shared reacquisition precedes mentor rediscovery. Only a proven
   anonymous result permits mentor pre-authentication. No private route or
   draft is restored across the role boundary.

`same actor` has one precise meaning in this design: the user authenticated for
the mentor ceremony must equal the server-side `user_id` that owns the active
`TutorProfile`, and the proof must be bound to that ceremony user. It does not
mean that the student/owner subject and mentor are the same person. It does not
allow a student session to be relabeled as tutor authority.

Handoff preconditions, in order:

1. If this browser has an incompatible owner/student session, the exact global
   NYAY-5 protocol ends it and the server rejects a conflicting session class;
   a canonical probe proves it absent. Timeout, NACK, ambiguity, or missing
   Web Locks/BroadcastChannel is `BLOCKED`, never a timer/storage fallback.
2. The mentor initiates a fresh, selector-free pre-authentication ceremony in
   its own browser. No owner-held cookie, invitation reference, URL value, or
   notification value is accepted as authority. The server sets the host-only
   HttpOnly `nyayone_mentor_bootstrap` (maximum 900 seconds) as a non-
   authorizing browser binding for pre-authentication idempotency and returns
   only a bounded generic next step.
3. The server selects the provider/policy and creates a server-held provider
   transaction. The pushed start and signed result use the non-public
   server-to-server adapter; the browser receives no NyayOne token, raw nonce,
   proof, actor, invitation, provider subject, or transaction identifier. A
   browser provider selector is a typed denial.
4. The mentor re-authenticates through that boundary. The external proof is
   fresh and bound to the server-held transaction, ceremony nonce, and same
   actor. Client header actors and lawyer browser state are not accepted.
5. Only after proof settles does the server derive exactly one live,
   unconsumed, purpose-valid protected invitation inside the same authority
   domain and current consent-policy version. A database uniqueness constraint
   prevents first-version selection ambiguity. Missing, multiple, expired,
   revoked, deleted, cross-owner, or cross-domain matches are generic denials.
6. The server requires exactly one current persisted
   `TutorProfileOwnershipProof` for the same mentor actor/profile, including
   provider-subject HMAC, assurance/policy, evidence digest/key, validity, and
   active undeleted rows. Lawyer verification or a positive Boolean alone is
   not tutor authority.
7. `verifyTutorIdentity` consumes the backchannel result and returns only the
   purpose disclosure and current consent version. It does not issue a session.
   For a recovery attempt, same-actor proof marks old actor/profile generations
   for mandatory revocation; verification itself does not revoke authority.
8. `exchangeTutorCeremony` requires the mentor's explicit acceptance of that
   exact disclosure/version and rechecks the invitation, profile proof,
   purpose, owner/student consent, authority domain, and—when the subject is a
   minor—current server-proven guardian authority plus the separate purpose/
   slice guardian consent. Limited mode or a revocation race denies sharing.
   Under lifecycle locks a recovery exchange revokes old actor/profile generations
   previously marked at verification, then the server consumes
   proof/invitation, activates the engagement, mints one `active` session, and
   appends PII-free issuance audit evidence in one transaction.
9. Cookie issuance occurs under the same global exclusive barrier. The client
   reacquires the shared lease and performs a canonical mentor-session probe.
   Private mentor UI mounts only after HTTP 200 proves the exact session class,
   purpose, and bounded projection.

Failures use a closed public inventory: `400 INVALID_REQUEST`,
`400 INVALID_IDEMPOTENCY_KEY`, and `400 ORIGIN_REJECTED` for malformed public
input; `401 AUTHENTICATION_REQUIRED` for absent cookie-derived authority;
`403 AUTHORIZATION_DENIED` as the single collapsed public code for wrong role,
unverified/current-proof, cross-user/owner/domain, invitation ambiguity,
provider selection, guardian or consent failure, and forbidden purpose;
`403 STEP_UP_REQUIRED` only for the distinct action-bound deletion condition;
`404 RESOURCE_UNAVAILABLE` for a protected resource that cannot be disclosed;
`409 IDEMPOTENCY_CONFLICT`, `409 CONCURRENT_STATE_CHANGED`,
`409 CEREMONY_REPLAYED`, `409 SESSION_CONFLICT`, and `409 SESSION_STALE` for
their bounded conflict classes; `410 SESSION_EXPIRED`,
`410 AUTHORITY_TERMINAL`, and `410 STEP_UP_EXPIRED` for terminal authority;
`429 RATE_LIMITED`; and `503 PROVIDER_UNAVAILABLE`. Every response uses the
fixed message `Request failed`, `Cache-Control: private, no-store`, `Vary:
Cookie`, and a strict PII-safe schema. Internal reasons are never returned.
Every failure guarantees no mutation unless it is the exact bounded outcome of
a previously committed same-key/same-payload idempotent replay.

## Data lifecycle, minimisation, and teardown

The data lifecycle covers invitation and session issuance, rotation, expiry,
revocation, logout, recovery, and deletion. Each transition is server-timed,
transactionally linearized, append-only audited, and reconciled with the
configuration-driven NYAY-19 retention posture. No statutory window is
hard-coded in this design, and teardown never restores or extends authority.

| Stage | Server transaction and authority effect | Data minimisation and audit | Required teardown/verification |
|---|---|---|---|
| Invitation issuance | Derive subject and authority domain from the owner session; create one purpose/policy/version-bound protected mentor match or exact replay through the separately approved prerequisite. For a minor, require current guardian authority and separate purpose/slice consent. | Store only the protected match, allowlist, expiry, keyed fingerprint, and PII-free audit event/version. | Partial uniqueness prevents ambiguous live matches; expiry/revocation/deletion/guardian withdrawal makes the generation terminal and unusable. |
| Bootstrap/challenge issuance | Create random server attempt and non-authorizing HttpOnly bootstrap binding; choose provider server-side; bind nonce/digest, pushed-start transaction, policy, fingerprint, and expiry at or before 900 seconds. Actor/invitation binding waits for proof. | Browser receives a generic next step only. Raw nonce/proof, invitation existence, provider/transaction token, and actor values are excluded from URLs, Web Storage, logs, evidence, and responses. | Consumed/expired/revoked challenge cannot be retried; a lost pre-cookie response expires unbound; recovery starts a fresh generic attempt. |
| Identity verification | Consume the non-public backchannel result; enforce same actor and the exact current persisted `TutorProfileOwnershipProof`; derive one protected invitation. Return only purpose disclosure/current consent version. | No raw provider proof in ordinary audit; access-controlled proof provenance retained only for configured need. | Failed/ambiguous result creates no authority. Recovery marks old actor/profile generations for mandatory revocation only after this same-actor proof; verification does not revoke them. |
| Scoped session issuance | Require explicit mentor acceptance of the unchanged disclosure/version; recheck profile proof, authority domain, purpose, invitation, student consent, and guardian authority/consent where applicable; consume proof and mint one keyed-digest `active` session. | Cookie is opaque; response omits actor/profile/domain raw IDs; immutable audit records only issuance class, generation, and purpose/policy/consent versions. | Global barrier and authoritative probe must prove the new session before private mount; server rejects conflicting session classes. |
| Active projection | Intersect the session ceiling with live consent/policy/engagement/profile proof/domain and guardian predicates on every request. Absolute session lifetime is at most 28,800 seconds and idle lifetime at most 1,800 seconds. | Default projection excludes DOB, unmasked mobile, raw identifiers, enrollment identifiers, and unrelated sections. Every field requires explicit current purpose policy and consent. | Any authority loss denies immediately; minor limited mode disables sharing; stale client display is untrusted and private UI unmounts on canonical 401. |
| Rotation | Under the global barrier and fixed DB locks, make the predecessor terminal `rotated_out`, create exactly one `active` successor with a fresh digest, append both PII-free events, then set the cookie. | No raw old/new token in database logs, audit, diagnostics, or evidence. | Old cookie never authorizes. With the predecessor binding, exact retry returns the bounded prior outcome and re-clears; without it, return generic unavailable and rely only on canonical probe. |
| Expiry | Server clock transitions or treats session/ceremony as expired at exact boundary before effect. | Keep only configured terminal metadata needed for security/accountability. | Cookie is cleared when presented; every request rejects expired generation; retention later erases/anonymises. |
| Revocation/consent withdrawal | Lock guardian/age, engagement, consent, profile proof, and sessions in fixed order; revoke targeted/all generations and append bounded events atomically. | Audit records stable reason class and versions, not narrative, guardian identity, DOB, or disclosed fields. | Revocation, DOB-to-minor transition, guardian loss, limited mode, and owner deletion win every read/verify/exchange/rotation race; subsequent reads disclose nothing. |
| Logout | Revoke the presented session idempotently, clear cookie under the exact global exclusive transition, complete teardown/end, reacquire shared, and probe authoritative absence. | No actor/profile details in an already absent or exact terminal replay. | Private state unmounts in every realm; missing locks/channel or ambiguous probe is fail-closed, with no timer/storage fallback. |
| Recovery | Initiation creates only a generic bootstrap attempt and revokes nothing. Same-actor backchannel proof marks every old actor/profile session generation for mandatory revocation; exchange locks and commits that revocation before issuing a successor. | Never reuse cookie, nonce, proof, or prior attempt; PII-free audit records bounded recovery stages. | Any uncertain proof or incomplete exchange-time revocation blocks recovery; initiation and verification cannot enumerate an actor or terminate another user's sessions. |
| Authority deletion | Require both a live mentor session and a distinct fresh server-proven action/fingerprint-bound step-up record plus HttpOnly `nyayone_mentor_authority_step_up` (maximum 300 seconds); lock the full graph, revoke sessions/proofs/invitations, and mark deletion before erasure. | Keep immutable PII-free audit events. Store reversible linkage only in a separately encrypted link record and cryptographically erase its row/per-subject key within the approved window. | Deleted authority cannot reactivate. Same-key exact terminal replay may repeat cookie clearing but never authority; restore requires privacy reconciliation, never direct rollback. |

Purpose projections are allowlists, not deny lists. A baseline tutoring purpose
may expose a display name or educational context only if the approved policy
and the exact consent grant enumerate those fields. DOB, unmasked mobile, raw
user/registration/profile/session IDs, raw institutional or bar-enrolment
identifiers, secrets, and unrelated activity are forbidden by default. The
mentor cannot export or persist a broader profile. Privacy exports for the data
subject include the subject's ceremony/consent history in a human-meaningful,
PII-safe format but omit security internals such as token digests, request
fingerprints, provider correlation, and internal identifiers.

Retention requirements:

- Windows and anonymise/delete mode are deployment configuration reviewed
  under the NYAY-19 process; the code must reject invalid or absent required
  values before mutation.
- One owned, non-overlapping retention worker processes expired ceremonies,
  sessions, proofs, and terminal idempotency outcomes in bounded batches and
  emits aggregate counts only.
- A privacy deletion freezes/revokes live authority before erasure. A backup or
  restore cannot return to service until post-backup privacy actions and every
  relevant session/proof capability are reconciled.
- Consent and reversible audit-link retention must be no broader than the
  approved legal/security purpose. Immutable events remain PII-free; DPDP
  erasure cryptographically destroys separately encrypted linkage without
  rewriting truthful event history. Raw proof, cookies, and session secrets
  have no audit or QA retention justification.

Every release must test this design with unit state/authorization matrices,
strict HTTP contracts, PostgreSQL concurrency and lifecycle races,
real-Chromium multi-tab/cookie/private-route behavior, privacy/credential
scans, and independent review. Evidence is synthetic or aggregate, exact-head,
SHA-256 sealed, and must prove negative cases and zero mutation. A structural
GREEN result for NYAY-29 is not an implementation PASS; implementation remains
the separately authorized NYAY-22 boundary.
