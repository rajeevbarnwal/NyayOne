# NYAY-85 — S-06 light R2 account recovery

Base: S-05 merge `7a6f599d2e82d607536efe0259ce1020541f7872`.
Owner merges; repository PUBLIC. NYAY-50 approval 15422 and the corrected
full-viewport R2 references remain unchanged. Dark mode is deferred (NYAY-51).

## Product and authority boundary

S-06 now uses the approved R2 mobile/desktop recovery composition and nine
states: entry, invalid number, submitting, challenge, wrong code, expired,
locked, network error and success. Presentation and server-state orchestration
are separate. No prototype sample identifier, code, timer or mock success is
introduced into production behavior.

Recovery is mobile-only. The controller uses the existing start/verify/complete,
OTP state/resend/cancel endpoints and cookies. Verification requires a complete
code and current server capability. A local countdown never grants resend;
server mutation results remain authoritative. No identity or code is stored in
browser storage. Duplicate mutations have a synchronous in-flight guard and
AbortSignals; responses after departure do not publish success or navigate.

Per owner decision NYAY-85:15602, successful verified-and-consumed recovery
stays on “Your account is ready” until Back to sign in leads to S-04. Recovery
does not authenticate. A recovered verified proof offers Retry reconciliation
and must complete before success; it is not a fresh code request. This is a
stable success view, not artificial navigation delay or component-only proof.

The registration browser producer follows this explicit return action. Existing
server start, verify, proof-consumption and no-password-reset assertions remain;
R2 selectors and explicit success assertions are additive/aligned. Mechanical
namespace inventory and the affected test seals account for the new S-06 files.
No workflow, reference, tolerance, or unrelated screen behavior is changed.

## Visual fixtures and reporting

All 9 states × 3 approved viewports have live-route fixtures: 390×844, 360×800,
1440×1024. Synthetic server projections pass through the normal API client;
the fixtures do not replace DOM, force disabled actions, or freeze navigation.
The display Date is fixed for deterministic countdown values; timers and
request handling continue. Submitting intentionally holds only its start
response until browser-context disposal. All mutations and payload shapes are
checked. Default captures use ordinary pointer interactions to leave fields
unfocused; keyboard behavior is tested separately.

Wrong-code 401 and network-error 503 browser resource diagnostics are retained
and classified only when the exact fixture declaration, observed method/URL/
status and Chromium message/location match once. Missing, duplicated or unknown
diagnostics still fail; page errors and actual network failures remain blocking.
The new helper, tests and fixtures are in the protected NYAY-66 bundle and need
fresh owner exact-content integrity approval. No self-approval is permitted.

Local same-host macOS reference/live comparisons are **diagnostic**, not pinned
Linux conformance. The hosted gate is the authority for final per-row metrics.
Existing references, historical artifacts and SHA labels are never relabelled.

## Intentional differences to propose, not self-approve

- Blank challenge Verify remains disabled until six valid digits and server
  authority are present. The prototype's enabled demonstration control cannot
  confer verification authority. Its disabled appearance can differ in pixels.
- Network failure says “We could not confirm whether your code was sent. Check
  your connection and try again.” The prototype's “Your code was not sent” would
  assert a fact the client cannot know when a response is lost. This text and
  resulting layout/pixels need a scoped owner disposition.

Report exact hosted deltas before binding any exception. No tolerance increase,
reference update, blanket waiver or claim of strict parity is authorized here.

## Validation and independent QA handoff boundary

Tests cover server capability, completion ordering, no post-departure completion,
busy Change, field normalization, errors, expiry/resend/lockout and stable
success. Additional fixture contracts cover all nine states and negative HTTP
diagnostic matching. Exact run counts and environment limitations belong in
the ticket's immutable head-qualified validation/evidence records.

Local publication rehearsal: frontend 1,898 passed / 1 skipped (140 files),
focused R2/gate contracts 158/158, S-06 presentation/controller 30/30, Python
policy 600/600, workflows 14/14, immutable migration ledger 15 revisions and
six evidence manifests / 319 files. TypeScript and build pass; ESLint has zero
errors and four unused legacy S-06-helper warnings in V34Screens.tsx. The Python
policy rehearsal used Python 3.13 / PyYAML 6.0.3; three initial watchdog failures
were process-inspection sandbox denials, then the complete suite passed with
that read permission. Native database/browser campaigns await the hosted run;
synthetic Chromium execution is not real-backend or physical-device proof.

Keep NYAY-85 In Progress until the actual hosted rows pass or all residuals have
scoped owner approval and CI is green. Then publish reference/before/after
comparison, per-row gate verdicts, accessibility results, and test cases for
backend-connected flows, keyboard/real-device behavior and cancellation races.
Attach self-contained preview.svg alongside HTML/PNG. Label a screenshot
composition as a presentation derivative, not a newly executed QA run. Require
independent Claude QA to publish its own preview.svg, actual results and explicit
NOT TESTED limits before owner review/merge. No independent pass is claimed by
the implementation evidence.
