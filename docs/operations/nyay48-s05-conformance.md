# NYAY-48 — S-05 light Revision L conformance

Starts from PR #47 merge `2d4a3f5dd195f9dca10412c92ff7093c510e63fa`.
The owner merges all PRs; the repository is PUBLIC. Existing references,
historical evidence and original SHA labels remain unchanged.

## Scope and owner disposition

NYAY-48 comment 15129 / NYAY-47 comment 15128 approve removing the persona and
language presentation controls after identifier submission on S-05, for both
mobile and email login. The original classification-pending issue description
is superseded, not a request to reopen NYAY-12. S-04/S-08/S-09 context controls
remain. The shared OTP component's changes are gated to `purpose === 'login'`.

Match Revision L's topbar/brand/main reading order and inert legal footer on
S-05 only. Correct the Change action typography, inline server-metadata layout,
metadata emphasis and narrow-screen primary-icon shrink. Add the prototype's
hidden One-time code text without changing the existing six-digit input name.
No production path, backend endpoint, reference, tolerance or evaluator changes.

## Authentication preserved

Keep six-digit numeric/paste/autofill, masked mobile/email destination, server
expiry/resend/attempt/lockout authority, existing verify/resend/change routing,
and fail-closed pending-flow checks. An empty Verify control stays disabled;
the reference prototype's enabled demo button is not permission to weaken this.
Existing accessible names distinguish Change mobile number / Change email
address, Six digit code, and Verify and continue. No identity browser storage.

S-09 retains its previous context callbacks, reading order, footer links and
OTP handlers. This ticket does not redesign signup verification or other screens.

## Tests-first and producer alignment

- New rendered-markup/source contracts: initial 10 expected failures / 15 passes,
  then 25 passes after the S-05 change. Two additional CSS contracts failed
  before the icon-shrink/metadata-weight correction, then all 27 passed.
- Existing NYAY-8 S-05-positive context expectation becomes four explicit
  absence checks (mobile/email, pending/loading); S-04/S-08/S-09 positives remain.
- Producer/source contracts: 7 expected failures / 34 passes before correction,
  then all 41 pass. NYAY-7 explicitly checks no S-05 context. The real Wave-3
  persona-cancellation test now travels S-05 Change mobile number → S-04 →
  Change persona. Its real cancellation, deferred response, retired OTP rejection,
  fresh login/session and server-countdown assertions remain. Only the pending
  cancellation route expectation changes from S-05 to S-04.
- All 17 Wave-3 record sites and 137 row identities remain. NYAY-7's 120 canonical
  and 350 expanded row identities remain. No historical image/manifests rewritten.

Affected producer/test files are outside the protected NYAY-66 bundle and have
no digest seals; no seal or namespace-inventory update is needed. The only new
frontend path is a test, excluded by the existing namespace test-source rule.
The protected bundle stays
`d87f89d14e8f56427e1e9e921864c887d193c87f92961186936fba64e5195bb1`.

Local validation: frontend 1,807/1,807 with no skips; typecheck, lint and build
pass; Python policy 600/600; workflows 14/14; namespace 142 production files /
22 compatibility literals / 17 self-tests; six evidence manifests / 319 files;
15 immutable migration revisions. Synthetic API/browser behavior passes 86/86
across mobile/email at 390 and 1440 pixels, with zero axe violations. Native
database and hosted exact-head results are recorded separately on the ticket.

## Visual and QA reporting boundary

Local same-host macOS captures at 390×844, 360×800 and 1440×1024 are diagnostics,
not the pinned Linux hosted gate. Approved S-05 gate rows are 390×844 and
1440×1024, light, default OTP state. Email and other OTP states receive functional
coverage but must not be described as additional approved full-page visual rows.

Retained accessible names and the blank-Verify disabled guard differ from the
prototype's control metadata. Report exact hosted metrics before proposing any
scoped owner exception. No self-approved exceptions; unchanged tolerances.
Text, headings, dynamic-region geometry, overflow and accessibility remain
independently checked. A green report-only job alone is not S-05 conformance.

Keep NYAY-48 In Progress until genuine effective conformance and green CI.
Then attach reference/before/after comparison sheets, exact-head gate results,
accessibility findings and tester notes; include a self-contained `preview.svg`
alongside HTML/PNG. The independent Claude QA must also attach `preview.svg`.
Label synthetic/emulated, real-backend, physical-device and spoken-screen-reader
coverage separately. Owner relays QA, reviews and merges; Codex merges nothing.
