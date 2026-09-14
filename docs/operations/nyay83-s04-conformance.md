# NYAY-83 — S-04 light Revision L conformance

S-04-only implementation, starting from PR #45 merge
`5d2e64b3dba1e8c7beb8dfc6c381ce39537ee819`. The repository is public;
the owner merges all PRs. Historical evidence and reference files stay unchanged.

## Narrow corrections

- Read the desktop top bar before the brand panel and main content, matching
  their visual order. Other screen call sites are unchanged.
- Use the prototype's visible `Mobile Number` label casing.
- Centre each channel icon and label with the prototype's 7px gap. The CSS rule
  is scoped to S-04; shared channel styling is unchanged.

Tests-first: the initial 11 contracts produced 2 expected failures (DOM order
and field label), then 11 passes. The additional channel-layout contract failed
before the scoped CSS correction, then all 12 passed. Assertions distinguish
server-rendered/source contracts from executable cancellation-helper tests.

## Preserved authentication behavior

Mobile input starts empty. Channel availability is server-projected and
fail-closed; email is enabled only by the existing server projection. Keep
numeric telephone entry, validation, non-enumerating copy, existing OTP endpoints,
and navigation to S-05 after accepted OTP start. Change retires server OTP
authority before returning to S-03 and refuses navigation on cancellation
failure. No browser identity persistence, password mode or new auth feature.

## Reference differences requiring disposition

The original NYAY66 Revision L reference has no Student/Change/English row and
contains an example mobile value. NYAY-8's approved authentication-context
supersession requires that row and an empty field. The context adds 48px plus
the existing 13px form gap: the subsequent form controls move down by 61px.
NYAY-12's server-enabled email projection also changes the mobile helper copy.
These are intentional functional deltas, not permission to remove controls,
populate a real input with a sample, disable email, or modify references.

Current S-04 additionally retains the older `Send one time code` accessible
name and interactive desktop legal footer. The owner has been asked whether to
align the name to `Send Code` and make only S-04's footer inert like Revision L.
Neither pending correction is silently included in this PR revision.

The raw S-04 gate is **NONCONFORMANT**, not a strict PARITY result. Exact-head
hosted screenshots and numbers must be reviewed before any owner-approved
exception is added. No exceptions, tolerances, evaluator rules, enforced-screen
settings or reference bytes are changed by this implementation. A green
report-only workflow is not sufficient to move NYAY-83 to Testing.

## Validation and handoff boundary

Local checks include frontend typecheck/lint/build and the complete frontend
suite, policy/security contracts, workflow/namespace checks and synthetic
browser diagnostics at 390x844, 360x800 and 1440x1024. Same-host macOS reference
renders are diagnostic only, not the pinned Linux hosted gate result. Synthetic
API/emulated-browser checks are not real-backend, physical-device or spoken
screen-reader evidence.

The protected NYAY66 bundle remains byte-identical at
`d87f89d14e8f56427e1e9e921864c887d193c87f92961186936fba64e5195bb1`.
No namespace inventory update is required: the new test file is excluded by
the existing test-source rule; no new production path is added.

Move to Testing only after genuine S-04 conformance or explicit owner-approved
exact-image exceptions. The eventual handoff must include reference/before/after
comparisons, actual gate numbers, accessibility findings, channel and OTP routing,
validation/retry/cancellation and keyboard tests, real mobile-keyboard/backend
cases and explicit coverage gaps. Attach a self-contained `preview.svg` alongside
the HTML sheet (PNG companion where useful), verify downloaded hashes, and
require the same preview attachment for independent Claude QA.
