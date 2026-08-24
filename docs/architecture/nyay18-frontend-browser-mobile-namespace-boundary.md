# NYAY-18 frontend browser and mobile namespace boundary

Status: implementation and release contract for NYAY-18. This document is
normative for shipped frontend identity, browser compatibility cleanup,
service-worker cache ownership, and Capacitor metadata.

NYAY-18 changes product namespaces; it does not create identity or authority.
The authenticated server session remains the only student actor selector, and
the server-authoritative NYAY-5 boundary remains unchanged. A browser key,
event, global, route, package name, or mobile application ID can never grant a
role, select a profile, prove completion, or authorize a cookie operation.

## Scope and non-goals

This boundary owns active frontend package and display identity, browser
storage names, process-only browser globals, service-worker caches, downloaded
artifact names, and Capacitor application metadata. It also owns the bounded
retirement seam for inherited browser names.

It does not rewrite historical database migrations, sealed evidence,
traceability references, public organization UUIDs embedded in migrations, or
the shared Atlassian tenant name. It does not import any inherited production,
staging, subscriber, browser, or mobile data. A later data import is a separate
migration with its own compatibility and security review.

## Exact active namespace map

The following map is closed for this release. A new persistent key, prefix,
cache, browser global, package identity, or mobile identifier requires an
explicit contract update, tests, and independent review.

| Surface | Exact NyayOne name | Boundary |
|---|---|---|
| Frontend package and lockfile root | `nyayone-frontend` | Build identity only. It grants no runtime authority. |
| Display and Capacitor application name | `NyayOne` | User-visible product identity. |
| Capacitor application ID | `com.nyayone.app` | iOS bundle and Android application identity. |
| Service-worker shell cache | `nyayone-shell-v1` | Fixed public shell and same-origin built assets only. |
| Brand mark asset | `/brand/nyayone-mark.svg` | Public UI asset path; it grants no runtime authority. |
| Theme preference | `nyayone.theme.v1` | Device preference; value is exactly `light` or `dark`. |
| Reserved locale preference | `nyayone.locale.v1` | Future device preference; it is not identity or session state. |
| Retired demo-auth replacement family | `nyayone.auth.${role}.v1` | Memory-default compatibility service. Production student authority never comes from it. |
| Student report service | `nyayone.student.reports.v1.` + actor ID | Explicitly injected store only; default application storage is memory-only. |
| Student reminder service | `nyayone.student.reminder-prefs.v1.` + actor ID | Explicitly injected store only; default application storage is memory-only. |
| Lawyer draft workspace | `nyayone.lawyer.draft-workspace.v1.` + workspace ID | Prototype/workspace state, never authentication. |
| Lawyer current-workspace pointer | `nyayone.lawyer.draft-workspace.v1.current` | Workspace navigation only. |
| Lawyer review workspace | `nyayone.lawyer.review-workspace.v1.` + workspace ID | Review state, never authentication. |
| Lawyer filing workflow | `nyayone.lawyer.filing-workflow.v1.` + workspace ID | Workflow state, never server authorization. |
| Auth refresh event | `nyayone:auth-change` | In-process notification only. |
| Student authority-loss event | `nyayone:student-auth-changed` | In-process notification after ordered cleanup. |
| Student transition-start event | `nyayone:student-auth-transition-started` | In-process unmount signal, not authority. |
| Cross-tab Web Lock | `nyayone.student.auth-session.v1` | Shared/exclusive cookie-rotation barrier. |
| Cross-tab transition channel | `nyayone.student.auth-transition.v2` | Identity-free start/ack/nack/end coordination. |
| Test-selected video transport global | `__nyayoneVideoTransport` | Process-only deterministic test seam; never durable identity. |
| Fake video-room global | `__nyayoneVideoRoom` | Process-only deterministic test seam. |
| Credential download | `nyayone-credential-qr.png` | Download filename only. |
| Clinical export schema | `nyayone.clinical-export.v1` | Export format marker, not profile authority. |
| Clinical export download prefix | `nyayone-clinical-hours-` + timestamp and extension | Download filename prefix only; it is never actor or session authority. |
| Case display/reference prefix | `NYAY-CASE-` + identifier | Display/reference only; never authentication, payment, or session authority. |
| Invoice display/reference prefix | `NYAY-INV-` + identifier | Display/reference only; never authentication, payment, or session authority. |
| Internship display/reference prefix | `NYAY-INT-` + identifier | Display/reference only; never authentication, payment, or session authority. |

`nyayone.auth.${role}.v1` is the literal code pattern; it currently produces
role-specific keys such as `nyayone.auth.lawyer.v1`. Application code deletes
the student variant and never derives a production student session from it.
The report, reminder, and lawyer workflow services may accept a store for
isolated tests, but the application default is memory-only. Moving any of
those values into durable browser storage is a new security decision, not a
namespace-only refactor.

## Delete-only compatibility inventory

With the one theme exception below, inherited values are untrusted and
delete-only. Compatibility code may enumerate their key names and remove them;
it must never read, parse, copy, display, log, transmit, or rewrite their
values.

### Exact localStorage keys

- `legalsaathi.student.profile.v1`
- `legalsaathi.student.onboarding.v34`
- `legalsaathi.internship.applications.v1`
- `legalsaathi.clinical.export-audit.v1`
- `legalsaathi.student.cleanup-registry.v1`
- `ls-auth-student`
- `ls-auth-lawyer`
- `ls-locale`
- `ls-reviewer`
- `ls-onboarding-seen`

### Retired localStorage prefix families

- `ls-reports-`
- `ls-reminder-prefs-`
- `ls-draftws-`
- `ls-review-`
- `ls-filing-`

Every key beginning with one of those prefixes is owned by the retirement
boundary. There is no suffix allowlist and no actor registry. Legacy report,
reminder, draft, review, and filing values are private data, so they are not
migrated to the new prefixes.

### Exact sessionStorage keys

- `legalsaathi.student.registration.v2`
- `legalsaathi.student.privacy.export.v1`
- `legalsaathi.student.privacy.delete.v1`

These registration and privacy-request references are also delete-only. The
server and HttpOnly flow/session cookies are the refresh-safe authority.

### Retired CacheStorage names

The service worker owns `nyayone-shell-`, `ls-shell-`, and
`legalsaathi-shell-` cache-name prefixes. Activation keeps only
`nyayone-shell-v1` and retires other owned names. A cache outside those exact
prefixes is unrelated and must be preserved.

## Sole theme one-shot migration

`ls-theme` is the sole compatible legacy value. The root browser bootstrap
applies this exact order:

1. Read `nyayone.theme.v1` first. A valid new value wins.
2. Only when the new value is absent or invalid, read `ls-theme` at most once.
3. Copy only a valid `light` or `dark` value to `nyayone.theme.v1`.
4. Remove `ls-theme` whether its value was valid, invalid, or superseded.
5. Invoke the complete delete-only local purge after that decision.

No locale, reviewer flag, onboarding marker, actor data, profile data, auth
snapshot, or workflow data crosses namespaces. When storage is inaccessible,
the migration reports incomplete without exposing the value or crashing the
public shell. A later invocation sees the new theme and does not read the
removed legacy value again.

## Bounded purge algorithm

Web Storage cleanup freezes one finite, name-only generation before it mutates
storage. It processes that frozen generation in slices of at most 256 matching
keys, calls `removeItem` for each slice, and re-enumerates key names to verify
that slice made progress. After the frozen generation is processed, exactly
one final name-only generation scan must be empty. Concurrent additions or
re-creations make the result incomplete; the purge never chases them in an
attacker-controlled loop. Every removal batch therefore contains at most 256
matching keys, including when more than 256 unrelated keys precede the first
match.

The algorithm:

- never calls `storage.clear()`;
- never reads a delete-only legacy value with `getItem`;
- preserves every unrelated key and value;
- validates every observed length as a finite, nonnegative safe integer before
  enumeration and treats an invalid or inaccessible length, failed key
  enumeration, failed removal, or silent no-progress removal as incomplete;
- returns the verified removal count, batch count, maximum batch size, and
  complete/incomplete verdict; and
- cannot loop forever on a non-conforming Storage implementation.

Exact current actor report/reminder keys are added to logout and actor-rotation
cleanup. The retired prefixes remain exhaustive so data from an older realm or
unknown historical actor is removed without persisting or reading an actor
registry.

## Bootstrap and session lifecycle

The production order is deliberate:

1. `main.tsx` retires the exact legacy sessionStorage inventory before
   `ReactDOM.createRoot` can render any route.
2. The root theme initializer performs the sole theme migration and complete
   local purge during initial render, before session-discovery effects run.
3. The student auth provider starts in `pending`, acquires its persistent
   shared Web Locks lease, and clears browser/process context before the
   authoritative cookie session probe.
4. An authenticated response is applied only after cleanup succeeds and the
   exact server actor is observed. Only then may a private student route mount.
5. Logout, expiry, revocation, actor change, and accepted deletion repeat the
   same cleanup under the shared/exclusive transition protocol. Canonical
   authority-loss responses unmount private UI immediately.
6. A successful cross-tab cookie transition publishes `end` before releasing
   the exclusive lease, reacquires the shared lease, and only then permits
   private rediscovery.

The pre-React session purge is public-safe: disabled storage does not crash the
anonymous shell. It is not trusted as proof of cleanup. Before authenticated
private state can mount, `clearStudentBrowserContext` repeats both local and
session retirement. An incomplete verdict makes authenticated discovery fail,
causes a transition NACK where applicable, denies the cookie operation, and
private routes remain `unavailable`. Missing Web Locks or
BroadcastChannel support has the same fail-closed result; there is no timer or
storage fallback.

The legacy theme is non-sensitive and intentionally excluded from the
student-session authority verdict after the one-shot migration. Every private,
actor-derived, auth, workflow, onboarding, registration, and privacy-reference
family is rechecked at the private boundary. Reload also erases all process-only
draft and actor state.

## Cache retirement and offline behavior

The service worker uses `nyayone-shell-v1`. On activation it enumerates owned
CacheStorage names and requests deletion of every owned name other than the
current cache in batches of no more than 256. The real-browser acceptance gate
must inspect CacheStorage afterward; a failed or surviving retired cache cannot
be certified merely because the activation handler settled.

Only `/index.html` and eligible same-origin built assets can enter the shell
cache. API traffic, non-GET requests, cross-origin resources, authorization-
bearing requests, and route aliases are never cache keys. A failed navigation
may receive only the public shell; the live session guard still resolves
authority server-side before mounting private content. Offline cache contents
never establish a session or profile owner.

## Mobile metadata boundary

The shipped Capacitor configuration is exactly:

- application ID `com.nyayone.app`;
- application name `NyayOne`;
- web directory `dist`; and
- Android server scheme `https`.

The package and lockfile root are both `nyayone-frontend`. Native iOS and
Android projects, signing identities, associated domains, URL schemes, push
entitlements, privacy manifests, icons, and store records must be generated or
synchronized from the exact reviewed candidate. They must be inspected before
store submission; a web-config rename alone does not prove native bundle
readiness. Once an app is registered or released, changing
`com.nyayone.app` creates a different mobile application rather than upgrading
the existing one.

No inherited bundle ID, application ID, display name, shared container,
keychain group, deep-link scheme, push topic, or store listing may be reused
implicitly. Adding any such compatibility is a separately reviewed migration.

## Required QA gates

### Static and native gates

The candidate must pass, without allowlisting a new legacy writer or weakening
a mutant:

```text
python3 scripts/ci/test_nyay18_namespace_boundary_doc.py
python3 scripts/ci/test_nyay18_namespace_policy.py
python3 scripts/ci/check_nyay18_frontend_namespaces.py --output <evidence>/summary.json
cd frontend && npm run test:run
cd frontend && npm run typecheck
cd frontend && npm run lint
cd frontend && npm run build
```

The namespace policy scans the complete shipped frontend source inventory,
requires the exact metadata and runtime counts, and permits legacy literals
only in hash-sealed compatibility sources with exact occurrence counts. Its
planted-mutant self-test must prove that visible inherited branding, an
unapproved legacy key, a new source file, changed compatibility code, metadata
drift, and an unsafe source node all fail closed. CI workflow policy also seals
the detector, planted-mutant tests, namespace contract, exact actions, required
commands, evidence manifest, privacy scan, and required aggregator.

The detector is a bounded static projection, not a proof against arbitrary
JavaScript evaluation. It resolves direct literals, escapes, literal joins and
concatenation, simple constant propagation, templates, and fixed numeric
`String.fromCharCode`/`String.fromCodePoint` calls. Arbitrary evaluation or
obfuscation remains a residual risk covered by the mandatory production
Chromium identity and namespace observations, not by a claim of complete
JavaScript interpretation.

### Real-browser gate

Static scanning is necessary but not sufficient. The same candidate must run a
real production Chromium build with the service worker enabled. The matrix must
cover mobile and desktop viewports, a fresh profile, reload/StrictMode,
pre-seeded exact legacy keys, more than 256 matching keys, more than 256 leading
unrelated keys, each retired prefix, both theme precedence cases, invalid theme,
inaccessible storage, failed removal, cache activation, logout, expiry,
revocation, actor rotation, canonical authentication loss, and accepted account
deletion.

The real production Chromium evidence must prove:

- only exact NyayOne active names remain;
- delete-only values never enter DOM, URL, history, console, network, new
  storage, JavaScript-readable cookies, IndexedDB, or CacheStorage;
- unrelated keys and caches remain byte-for-byte unchanged;
- retired owned caches disappear and private/API responses are not cached;
- unsupported Web Locks or incomplete cleanup mounts no private content and
  performs no cookie operation; and
- the inherited NYAY-5 contract inventory and all of its planted contract
  mutants remain exact. This NYAY-18 producer does not relabel NYAY-18 probes
  as NYAY-5 execution: the separate exact-head `nyayone-nyay5-required`
  production gate must also be green before the combined wave can merge.

The hash-sealed loopback `nyay18-preview-server.mjs` is evidence-authoritative
for the hostile public-asset and install-shell probes. The live asset response
is expected to execute, but its server-observed Cookie-header count must be
zero and it must never enter the current shell cache. The separately armed
private/no-store shell response must neither execute nor enter that cache; the
normal public shell must be installed and must work as an offline fallback
before any test-only cache mutation.

The NYAY-18 browser report row `inherited_nyay5_contract_integrity` proves only
the sealed NYAY-5 assertion-contract and planted-mutant integrity reused by
this producer. It does not execute or replace the independently required
NYAY-5 workflow. The real NYAY-5 exact-head producer remains a separate
required gate and must pass for the same candidate before acceptance.

Browser screenshots and raw profiles are privacy-sensitive evidence. They must
be sanitized, inventoried, sealed, scanned, and verified before upload.

### Exact-head evidence

All static, native, build, PostgreSQL-dependent inherited gates, and Chromium
gates must run against the exact candidate HEAD and tree intended for review.
Record the full commit SHA, tree SHA, parent, source-inventory digest, namespace
contract digest, browser report digest, and evidence-manifest digest. Run
`git diff --check`, require the intended worktree to be clean, and do not change
source after evidence is produced. A stale local run, a different merge tree,
or evidence copied from an earlier head does not certify the candidate.

## Rollback and security constraints

Do not roll back by restoring a legacy writer, legacy visible brand, broad
storage deletion, client-selected actor, or browser-derived auth snapshot. A
rollback must be a forward repair using an explicitly reviewed NyayOne
namespace. If an older web or mobile client can recreate retired names, keep
private access disabled or enforce an independently reviewed minimum-client
boundary until the forward cleanup is deployed.

Never use `storage.clear()`, wildcard cookie deletion, broad CacheStorage
deletion, or an unrelated-origin cleanup. Never copy private legacy values into
new keys, telemetry, evidence, logs, network bodies, query strings, or globals.
Never weaken the server-authoritative NYAY-5 boundary, fail-closed route map,
Web Locks protocol, canonical-401 memory-only reauthentication handoff, or
server-side role checks to make a namespace rollback appear compatible.

An older service worker may recreate an inherited cache after rollback. The
forward release must reclaim only the exact owned cache prefixes and verify the
result in Chromium. Mobile rollback must preserve the registered
`com.nyayone.app` identity and signing lineage; shipping an inherited app ID or
changing the application ID is not a rollback of the same application.

Historical database migrations and sealed evidence remain immutable. Any
future compatibility exception needs a separate specification, exact source
and occurrence allowlist, hash sealing, planted negative tests, privacy review,
real-browser evidence, and independent security approval before code is
changed.
