# NYAY-29 tutor/lawyer ceremony sequence diagrams

Status: normative, design-only artifact. NYAY-22 requires separate approval and
an implementation handoff. Nothing here implements mentor authentication or
changes the administrator-only M-01 boundary.

## Normative authority and notation

The platform is server-authoritative. A separately approved owner-engagement
surface creates `MentorInvitation` and `PurposeConsentGrant` records before
this nine-operation mentor ceremony begins. Those records remain server-side:
the student or owner sends no invitation capability, URL, token, cookie, QR
code, actor identifier, or proof to the mentor. Possession of a notification
does not disclose invitation existence and grants no authority.

The server owns these lifecycle records:

- a non-authorizing bootstrap attempt;
- `MentorCeremony`: `pending_invitation -> challenge_issued -> proof_verified
  -> exchanged`, or terminal `expired|revoked|deleted`;
- `MentorSession`: `active`; rotation makes its predecessor `rotated_out` and
  its successor `active`; terminal states are
  `expired|revoked|logged_out|deleted`; and
- a purpose-bound `MentorEngagement` linking one owner/student subject to one
  verified, current, active `TutorProfile` through an explicit consent version
  and an allowlist of minimum profile slices.

Each relation carries the same server-generated authority-domain key. Composite
foreign keys and service predicates prohibit an invitation, consent, ceremony,
engagement, `TutorProfile`, or session from joining across authority domains or
tenants. This relation-based authority-domain isolation is rechecked inside
every effect transaction. Raw domain, actor, owner, profile, and session keys
never cross the API.

Browser state has no authority. The only browser-held correlators are opaque,
Secure, host-only, HttpOnly cookies:

| Cookie class | Meaning | Retirement |
|---|---|---|
| `BootstrapCookie` | Non-authoritative binding between a public browser entry and a server-side pre-auth attempt. | Retired only after `CeremonyCookie` issuance succeeds, or on bootstrap expiry/cancellation. |
| `CeremonyCookie` | Binds the browser to server-held challenge/provider/verification state; it does not prove identity or eligibility. | Retired only after exchange commits, or when that ceremony becomes terminal. |
| `MentorSessionCookie` | Selects one isolated, purpose-bound mentor-session row. | Rotated, revoked, logged out, expired, or deleted independently of bootstrap/ceremony cookies. |
| `StepUpCookie` | Short-lived, single-purpose proof of a completed `authority_deletion_step_up` ceremony. | Consumed and retired by authority deletion, or retired at expiry. |

No cookie value, challenge, nonce, identity proof, provider selector, query
token, idempotency key, or session secret appears in Web Storage, URLs, logs,
evidence, browser-readable state, or audit. The external identity provider
delivers its result to the Auth API over an authenticated server-to-server
backchannel; browser application code submits neither raw proof nor a provider
choice.

All owner and mentor cookie operations share the **single existing NYAY-5 Web
Locks barrier**, `nyayone.student.auth-session.v1`; no independent mentor lock
may race it. The exact order is persistent realm shared lease, per-request
shared lease through complete response observation, one exclusive cookie
operation, authoritative probes for every affected session class, transition
end publication before release, then realm shared reacquisition before private
rediscovery. Unsupported `navigator.locks`, peer NACK, incomplete private-state
cleanup, or failed probe blocks the cookie operation. There is no timer or
storage fallback.

Unsafe mutations require a trusted `Origin`, strict request schema, and
mandatory idempotency key. A same-key/same-canonical-payload retry returns the
same bounded committed result only when a remaining server-authenticated cookie
and canonical authoritative probe bind the caller to that result. A request
body alone can never replay authority after cookie retirement. Same key with a
different payload, or a concurrent different-key loser, returns a typed PII-safe
conflict with no mutation.

The typed failure inventory covers `anonymous`, `wrong-role`, `unverified`,
`cross-user`, `revoked`, `deleted`, and `stale-session`, plus replay, expiry,
consent withdrawal, guardian withdrawal, and relation-domain mismatch. Every
denial is non-enumerating. Future evidence must include unit, HTTP, PostgreSQL
concurrency, real-Chromium, privacy, and independent review gates; a
zero-executed or missing oracle cannot pass.

Audit is immutable, append-only, and PII-free. It records stable event/outcome
codes, purpose/policy versions, generation, coarse server time, and protected
relation references—never profile values, proof, cookies, secrets, or free
text. Per-authority-domain linkage is encrypted under a separately erasable
key. Approved erasure destroys that key and linkable verification material
(`crypto-erased`) while immutable aggregate audit facts remain truthful and
cannot reactivate authority, consistent with NYAY-19.

## Initiate and challenge

This `sequenceDiagram` starts from a public Browser entry, uses a
non-authoritative HttpOnly bootstrap cookie, and lets the mentor call the Auth
API to initiate. The challenge and `nonce` remain in the Ceremony store with a
server-clock `expiry`; no client-selected provider, invitation, owner,
`TutorProfile`, or `Origin`-bypassing query value participates.

```mermaid
sequenceDiagram
    autonumber
    actor Browser as Mentor Browser
    participant AuthAPI as Auth API
    participant CeremonyStore as Ceremony store
    participant IdentityProvider as External identity provider
    participant Audit as Audit ledger

    Note over Browser,Audit: Prior owner invitation and consent are server-owned prerequisites; no capability is transferred
    Browser->>AuthAPI: GET canonical public mentor-entry document
    AuthAPI->>CeremonyStore: Create bounded non-authorizing bootstrap attempt
    CeremonyStore->>Audit: Append bootstrap-start class only
    AuthAPI-->>Browser: Public shell + Secure host-only HttpOnly BootstrapCookie

    Note over Browser,AuthAPI: Browser acquires the single NYAY-5 exclusive barrier before any cookie transition
    Browser->>AuthAPI: POST /api/v1/auth/mentor/ceremony/initiate<br/>Origin + Idempotency-Key + requestedMentorRole + purposeCode + privacyNoticeVersion
    AuthAPI->>CeremonyStore: Resolve BootstrapCookie; lock bootstrap idempotency scope
    AuthAPI->>AuthAPI: Reject any client actor, invitation, profile, provider, consent-slice, proof, nonce, or query selector
    alt bootstrap absent/expired, untrusted Origin, malformed request, or incompatible owner/mentor session present
        AuthAPI-->>Browser: 400/401/409 non-enumerating MentorFailure; no ceremony mutation
    else same key and same canonical request already committed
        CeremonyStore-->>AuthAPI: Existing challenge projection and ceremony-cookie binding
        AuthAPI-->>Browser: Exact bounded replay under authoritative BootstrapCookie probe
    else same key with changed canonical request
        CeremonyStore-->>AuthAPI: IDEMPOTENCY_CONFLICT
        AuthAPI-->>Browser: 409; no mutation
    else new browser-bound attempt
        CeremonyStore->>CeremonyStore: Generate nonce and challenge; persist digest, policy, attempt budget, and expiry only
        CeremonyStore->>CeremonyStore: pending_invitation -> challenge_issued; invitation remains deliberately unresolved
        CeremonyStore->>Audit: Append challenge-issued class without identity or invitation fact
        CeremonyStore-->>AuthAPI: Generic bounded status, next step, and relative expiry
        AuthAPI-->>Browser: 202 + issue CeremonyCookie + retire BootstrapCookie in one exclusive operation
    end

    AuthAPI->>IdentityProvider: Start server-selected identity policy and server-held correlation
    IdentityProvider-->>AuthAPI: Later authenticated backchannel result; no browser callback token
    AuthAPI->>CeremonyStore: Bind provider result digest to exact unexpired ceremony nonce
    Note over Browser,IdentityProvider: Browser receives only generic pending/continue state; no raw identity proof or provider selector
```

`initiateTutorCeremony` neither reads nor confirms an invitation. It is
deliberately indistinguishable for potentially eligible and ineligible mentors.
The owner prerequisite may remain active on another device, but a same-browser
owner context must first be ended and authoritatively probed absent under the
global barrier. A concurrent owner login cannot overlap initiation or later
exchange.

## Verify and mint an isolated mentor session

This `sequenceDiagram` consumes the server-held `identity proof`, derives
exactly one invitation only afterward, verifies current `TutorProfile ownership`,
then mints a `server-derived` isolated mentor session in an `HttpOnly` cookie.
The mentor explicitly accepts the bounded purpose only in exchange with
`acceptPurpose=true`; verification itself grants no capability.

```mermaid
sequenceDiagram
    autonumber
    actor Browser as Mentor Browser
    participant AuthAPI as Auth API
    participant IdentityProvider as External identity provider
    participant CeremonyStore as Ceremony store
    participant TutorProfile as TutorProfile store
    participant GuardianState as Consent and guardian authority
    participant SessionAuthority as Session authority
    participant Audit as Audit ledger

    Browser->>AuthAPI: POST /api/v1/auth/mentor/ceremony/verify<br/>Origin + Idempotency-Key + expectedCeremonyState only
    AuthAPI->>CeremonyStore: Resolve CeremonyCookie; lock challenge, provider result, and idempotency row
    CeremonyStore->>IdentityProvider: Validate backchannel signature, issuer, audience, nonce, freshness, and one-use status
    IdentityProvider-->>CeremonyStore: Server-verified subject and assurance provenance
    AuthAPI->>TutorProfile: Resolve exactly one profile from verified subject; no browser profile selector
    TutorProfile->>TutorProfile: Require ownership, active status, verified provenance, issuer/policy currency, proof freshness, and no revocation
    alt proof or profile absent, stale, unverified, substituted, revoked, or lawyer-only
        TutorProfile-->>AuthAPI: Uniform typed denial
        AuthAPI->>CeremonyStore: Consume attempt budget or terminally revoke exact ceremony
        CeremonyStore->>Audit: Append aggregate verification denial
        AuthAPI-->>Browser: 403/404/410 non-enumerating failure; no invitation fact and no session
    else same actor owns one current active TutorProfile
        TutorProfile-->>AuthAPI: Server-bound mentor actor and provenance digest
        AuthAPI->>CeremonyStore: Derive invitation by verified actor + role + purpose + authority domain
        CeremonyStore->>GuardianState: Lock exact current purpose consent, subject mode, and guardian state
        alt zero/multiple/cross-domain invitations, consent absent/stale, minor limited mode, or guardian authority absent
            GuardianState-->>AuthAPI: Uniform unavailable/forbidden result
            AuthAPI-->>Browser: 403/404/409 non-enumerating failure; no mutation
        else exactly one live invitation and permitted current consent
            GuardianState-->>AuthAPI: Bounded purpose, consent version, disclosure text, and minimum slice names
            CeremonyStore->>CeremonyStore: Bind actor/profile/invitation/domain; challenge_issued -> proof_verified; crypto-isolate raw proof
            CeremonyStore->>Audit: Append proof-verified class and provenance version only
            AuthAPI-->>Browser: 200 bounded disclosure + consentReceiptVersion; rotate CeremonyCookie only
        end
    end

    Browser->>AuthAPI: POST /api/v1/auth/mentor/ceremony/exchange<br/>Origin + Idempotency-Key + proof_verified + purposeCode + consentReceiptVersion + acceptPurpose=true
    Note over Browser,SessionAuthority: Exclusive global barrier serializes mentor exchange with owner login and all other cookie operations
    AuthAPI->>CeremonyStore: Lock ceremony, invitation, engagement, consent, idempotency, and authority domain
    AuthAPI->>TutorProfile: Recheck same-actor ownership and verification provenance/currentness
    AuthAPI->>GuardianState: Recheck consent version, minor mode, and guardian authority at exchange instant
    AuthAPI->>SessionAuthority: Probe both owner and mentor session classes; lock actor generations
    alt concurrent owner login committed first
        SessionAuthority-->>AuthAPI: Incompatible owner authority present
        AuthAPI-->>Browser: 409 CONCURRENT_STATE_CHANGED; no mentor session or cookie mutation
    else consent/guardian/profile/invitation/domain changed or terminal
        AuthAPI-->>Browser: 403/409/410 typed failure; retire CeremonyCookie only when terminal
    else ordinary mentor-session intent and every predicate is current
        CeremonyStore->>CeremonyStore: Record explicit purpose acceptance; activate exact engagement; consume challenge/invitation
        SessionAuthority->>SessionAuthority: Generate random bearer; persist digest, domain, purpose, scope ceiling, generation, and bounded expiry
        CeremonyStore->>Audit: Append acceptance and issuance classes without PII
        AuthAPI-->>Browser: 201 MentorSessionProjection + issue MentorSessionCookie + retire CeremonyCookie
    end

    Browser->>AuthAPI: GET /api/v1/auth/mentor/session under reacquired shared lease
    AuthAPI->>SessionAuthority: Canonical authoritative probe from MentorSessionCookie
    SessionAuthority->>TutorProfile: Recheck current verified ownership/provenance
    SessionAuthority->>GuardianState: Intersect live consent, guardian/minor mode, purpose policy, and scope ceiling
    alt any authority missing, stale, withdrawn, expired, revoked, deleted, or cross-domain
        SessionAuthority-->>AuthAPI: No active mentor authority
        AuthAPI-->>Browser: 401/410; private mentor UI remains unmounted
    else exact live authority
        SessionAuthority-->>AuthAPI: Minimum bounded MentorSessionProjection
        AuthAPI-->>Browser: 200; private mentor UI may mount after shared-lease reacquisition
    end
```

The same-actor predicate means verified ceremony subject equals
`active TutorProfile.user_id`; it never means mentor equals student/owner. A
legal credential alone is not tutor authority. The session scope and permitted
profile slices are the server-derived intersection of purpose policy, current
consent, current guardian/minor access mode, current engagement, current
profile provenance, and relation domain. DOB, unmasked mobile, email, and raw
identifiers are never projected.

If exchange committed but its response was lost, the retired CeremonyCookie
cannot be replaced by body replay. A retry bearing the same key and body is
resolved through the remaining MentorSessionCookie, a canonical
`getTutorSession` probe, and the durable idempotency/session relation. Only an
exact actor/domain/purpose match returns the bounded committed projection; no
cookie or body means `401` and never remints authority.

## Reject replay, expiry, and actor substitution

This adversarial `sequenceDiagram` rejects `replay`, an `expired` ceremony,
`cross-user` substitution, consent/guardian races, and concurrent session
operations with `no mutation` beyond bounded terminal/attempt evidence. Missing
and mismatched relations use the same `non-enumerating` shape.

```mermaid
sequenceDiagram
    autonumber
    actor Browser as Mentor Browser
    participant AuthAPI as Auth API
    participant CeremonyStore as Ceremony store
    participant TutorProfile as TutorProfile store
    participant Consent as Consent and guardian authority
    participant SessionAuthority as Session authority
    participant Audit as Audit ledger

    par consumed challenge under a different idempotency key
        Browser->>AuthAPI: POST verify/exchange after proof or invitation consumption
        AuthAPI->>CeremonyStore: Lock and compare one-use state
        CeremonyStore-->>AuthAPI: Already consumed/exchanged
        AuthAPI-->>Browser: 409 CEREMONY_REPLAYED; no cookie or session mutation
    and same key with a changed canonical payload
        Browser->>AuthAPI: Reuse key with changed purpose, version, or acceptPurpose
        AuthAPI->>CeremonyStore: Compare durable request fingerprint
        CeremonyStore-->>AuthAPI: Mismatch
        AuthAPI-->>Browser: 409 IDEMPOTENCY_CONFLICT; no mutation
    and expired challenge
        Browser->>AuthAPI: Verify/exchange after database-clock expiry
        AuthAPI->>CeremonyStore: Materialize expired terminal state once
        CeremonyStore->>Audit: Append expiry class
        AuthAPI-->>Browser: 410 AUTHORITY_TERMINAL; retire CeremonyCookie only
    and actor/profile substitution
        Browser->>AuthAPI: Verify while backchannel subject and bound profile relation differ
        AuthAPI->>TutorProfile: Compare server subjects and authority domain
        TutorProfile-->>AuthAPI: Ownership/domain mismatch
        AuthAPI-->>Browser: Uniform 404; no profile or invitation existence disclosure
    end

    par exchange K1
        Browser->>AuthAPI: POST exchange K1
        AuthAPI->>CeremonyStore: Acquire lifecycle locks
        CeremonyStore->>SessionAuthority: Commit exactly one active generation
        SessionAuthority-->>Browser: 201 MentorSessionCookie
    and exchange K2
        Browser->>AuthAPI: POST exchange K2
        AuthAPI->>CeremonyStore: Wait, then observe exchanged state
        AuthAPI-->>Browser: 409 CONCURRENT_STATE_CHANGED; no second generation
    and owner login races exchange
        Browser->>AuthAPI: Owner-login cookie operation requests same global exclusive barrier
        AuthAPI->>SessionAuthority: Serialize; loser re-probes both session classes
        SessionAuthority-->>AuthAPI: One authority class won
        AuthAPI-->>Browser: Loser blocked/409; never simultaneous owner and mentor authority in one realm
    end

    par guardian withdrawal commits before exchange
        Consent->>CeremonyStore: Revoke guardian/purpose consent under lifecycle locks
        CeremonyStore->>SessionAuthority: Revoke linked ceremony/session generations
        AuthAPI-->>Browser: Exchange returns 403/409/410; zero disclosure
    and minor limited mode becomes authoritative during exchange
        Consent->>CeremonyStore: Commit restricted access mode/version
        CeremonyStore->>SessionAuthority: Restriction wins lock/version race
        AuthAPI-->>Browser: No mentor issuance or profile projection
    and TutorProfile provenance expires or is revoked
        TutorProfile->>SessionAuthority: Commit stale/revoked verification provenance
        SessionAuthority->>SessionAuthority: Revoke affected active generations
        AuthAPI-->>Browser: 401/410 and private UI teardown
    end
```

Diagnostics contain only stage, typed code, elapsed-time bucket, and aggregate
counts. They exclude query strings, actor data, proof/provider data, consent
values, cookies, OTPs, tokens, idempotency keys, and session secrets. A denial
may consume a server-owned attempt budget or commit a terminal security state;
it cannot broaden scope, rebind a relation, or mutate another authority domain.

## Revoke, tear down, and return to owner context

This lifecycle `sequenceDiagram` covers rotation, recovery, `revocation`,
`logout`, deletion and expiry. Each `cookie` operation follows the one global
barrier, then an `authoritative probe`; no mentor or owner `private route`
mounts from browser memory.

```mermaid
sequenceDiagram
    autonumber
    actor Browser as Mentor Browser
    actor OwnerBrowser as Student / Owner Browser
    participant AuthAPI as Auth API
    participant CeremonyStore as Ceremony store
    participant TutorProfile as TutorProfile store
    participant Consent as Consent and guardian authority
    participant SessionAuthority as Session authority
    participant Audit as Audit ledger

    Browser->>AuthAPI: POST /api/v1/auth/mentor/session/rotate<br/>Origin + Idempotency-Key + MentorLifecycleRequest
    AuthAPI->>SessionAuthority: Lock exact cookie-derived active generation
    SessionAuthority->>TutorProfile: Recheck current ownership/provenance
    SessionAuthority->>Consent: Recheck purpose, consent, guardian/minor mode, and domain
    alt revoke/logout/expiry/deletion won the race
        SessionAuthority-->>AuthAPI: Terminal state
        AuthAPI-->>Browser: 409/410; no successor
    else rotation authorized
        SessionAuthority->>SessionAuthority: Predecessor -> rotated_out; insert successor active atomically
        SessionAuthority->>Audit: Append PII-free rotation class
        AuthAPI-->>Browser: 200 new projection + replace MentorSessionCookie only
    end

    alt explicit revocation
        Browser->>AuthAPI: POST /api/v1/auth/mentor/session/revoke<br/>Origin + Idempotency-Key + MentorLifecycleRequest
        AuthAPI->>SessionAuthority: Commit revoked state under exclusive barrier
        SessionAuthority->>Audit: Append revocation class
        AuthAPI-->>Browser: 200 MentorLifecycleOutcome + retire MentorSessionCookie only
    else explicit logout
        Browser->>AuthAPI: POST /api/v1/auth/mentor/session/logout<br/>Origin + Idempotency-Key + strict MentorLifecycleRequest body
        AuthAPI->>SessionAuthority: Commit logged_out state under exclusive barrier
        SessionAuthority->>Audit: Append logout class
        AuthAPI-->>Browser: 200 MentorLifecycleOutcome + retire MentorSessionCookie only
    else server-clock expiry or consent/guardian withdrawal
        AuthAPI->>SessionAuthority: Lock and materialize expired/revoked state before any effect
        SessionAuthority->>Audit: Append one terminal class
        AuthAPI-->>Browser: 401/410; retire MentorSessionCookie only
    end

    Browser->>AuthAPI: GET /api/v1/auth/mentor/session
    AuthAPI->>SessionAuthority: Canonical authoritative probe
    SessionAuthority-->>AuthAPI: No active mentor authority
    AuthAPI-->>Browser: Bounded denial; transition ends before exclusive-lock release

    Note over Browser,Audit: Recovery creates a non-authorizing attempt; it never revives stale authority
    Browser->>AuthAPI: POST /api/v1/auth/mentor/ceremony/recover<br/>Origin + Idempotency-Key + recovery intent
    AuthAPI->>CeremonyStore: Create fresh attempt/challenge; issue new CeremonyCookie
    CeremonyStore-->>Browser: 202 generic non-authorizing challenge
    AuthAPI->>CeremonyStore: verifyTutorIdentity consumes only later server backchannel result
    CeremonyStore->>TutorProfile: Require same actor and current verified ownership
    TutorProfile-->>CeremonyStore: Verified actor/profile binding
    CeremonyStore->>SessionAuthority: Mark all prior actor/profile generations for mandatory revocation
    SessionAuthority-->>CeremonyStore: Revocation set marked; no authority mutation yet
    CeremonyStore-->>Browser: 200 proof_verified bounded projection
    Browser->>AuthAPI: POST exchange with recovery intent + acceptPurpose=true
    AuthAPI->>SessionAuthority: Revoke all prior actor/profile generations and recheck current predicates atomically
    SessionAuthority->>Audit: Append recovery-wide revocation class
    SessionAuthority-->>Browser: 201 one new isolated session; retire CeremonyCookie separately

    Note over Browser,Audit: Authority deletion requires a separately exchanged, single-purpose step-up
    Browser->>AuthAPI: POST recover with intent authority_deletion_step_up
    AuthAPI->>CeremonyStore: Start non-authorizing step-up attempt
    AuthAPI->>CeremonyStore: verify after server-only identity backchannel
    CeremonyStore->>TutorProfile: Rebind exact same actor/profile with current provenance
    Browser->>AuthAPI: POST exchange intent authority_deletion_step_up + acceptPurpose=true
    AuthAPI->>SessionAuthority: Recheck live MentorSessionCookie and same actor
    AuthAPI-->>Browser: 200 issue short-lived HttpOnly StepUpCookie; retire CeremonyCookie; no new mentor session
    Browser->>AuthAPI: DELETE /api/v1/auth/mentor/authority<br/>Origin + Idempotency-Key + mentor and step-up cookies + strict deletion body
    AuthAPI->>SessionAuthority: Lock and revoke/delete all actor mentor generations
    AuthAPI->>CeremonyStore: Terminalize ceremonies/engagements and schedule configured erasure
    AuthAPI->>Audit: Append immutable PII-free deletion class; crypto-erase link key per policy
    AuthAPI-->>Browser: 202 deletion accepted + retire MentorSessionCookie and StepUpCookie independently

    Browser->>AuthAPI: Probe mentor session after deletion
    AuthAPI->>SessionAuthority: Canonical authoritative probe
    SessionAuthority-->>Browser: 410 AUTHORITY_TERMINAL; no private mentor route

    Note over OwnerBrowser,SessionAuthority: Return is fresh NYAY-8 owner authentication, never restoration or promotion
    OwnerBrowser->>AuthAPI: Start server-authoritative passwordless owner login under global exclusive barrier
    AuthAPI->>SessionAuthority: Require no live mentor class, issue fresh owner session after proof
    SessionAuthority-->>OwnerBrowser: New host-only HttpOnly owner cookie
    OwnerBrowser->>AuthAPI: Canonical owner-session probe under reacquired shared lease
    alt absent, unavailable, wrong role, different actor, or stale
        SessionAuthority-->>OwnerBrowser: Fail closed; no owner private route
    else exact authenticated owner actor
        SessionAuthority-->>OwnerBrowser: 200 canonical owner projection; private rediscovery may begin
    end
```

Recovery verification revokes every prior mentor generation before a recovery
exchange can mint a successor. A failed or abandoned exchange therefore leaves
the actor safely without old mentor authority. Deletion step-up is narrower: it
creates only a short-lived `StepUpCookie`, never a second mentor session, and
the delete operation requires both the still-live mentor cookie and that exact
same-actor step-up cookie.

Retention follows configuration approved under NYAY-19. Live authority is
revoked immediately; proof and linkable relation material are erased or
crypto-erased within the configured window; append-only PII-free audit remains
immutable for its approved purpose. Restore or recovery cannot reactivate a
terminal invitation, consent, ceremony, session, or deleted authority.

NYAY-22 must independently test every branch above—success, replay, concurrent
owner login, concurrent exchange, rotation, stale provenance, minor/guardian
restriction, consent withdrawal, expiry, revocation, logout, recovery, step-up,
deletion, Web Locks absence, and authoritative owner return—before any mentor
route or API ships.
