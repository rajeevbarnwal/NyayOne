# S-18 hosted calibration prerequisite

This is an owner-approved, capture-only prerequisite for PR #68. It contains no
product implementation, imported PNGs, new exceptions or enforcement promotion.

## Exact scope

- Add `s18-v32108` to the existing manual-only `nyay66-calibration.yml` selector.
  Keep `r2` and `revl` behavior unchanged. Both actor and rerun actor must be the
  owner, dispatch ref must be `main`, checkout credentials are not persisted,
  permissions remain read-only, and artifacts retain 14 days.
- Execute the S-18 calibrator from the trusted control checkout, never from the
  candidate. Verify the workflow's exact SHA-256 in the protected capture module
  as well as the repository policy seal.
- Read the existing canonical v3.2.1.08 ZIP (SHA-256
  `0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964`).
  Reuse the source loader to validate all 22 manifest members, the HTML,
  embedded fonts/logos and state inventory; execute no packaged helper scripts.
- Render only S-18: loading, loaded, saving, saved, invalid, conflict, network,
  forbidden and session, at 390×844 and 1440×1024. Generate 18 PNGs, each from
  three fresh-context samples required to be byte-identical.
- Fail closed on Chromium `149.0.7827.55`, Playwright `1.61.1`, `linux-x64` or
  font-byte mismatch. Record source and control commits, font stack, surface
  structure, PNG dimensions/digests and all three sample digests.
- Use the frozen library's capture/bare mode. Normalize only the reviewer
  `.vp` border radius to zero (desktop retains an 8px radius otherwise).
  Capture the browser viewport, not an expanded full-page image. The mobile
  invalid state extends below the fold; preserve its content height in surface
  metadata and do not resize, reflow or restyle the application to fit.
- Publish artifacts only. Never import, commit, push, merge, self-approve or
  dispatch another run. No PR reference generation is introduced.

## Unchanged

The canonical ZIP, Revision L/R2 sources, existing reference PNGs, all 74 blocking
light rows, live evaluator, approval reader, policy tolerances, enforcement list,
existing exceptions, product files and historical evidence are unchanged.

Optional manual Save/Discard is **deferred pending user feedback — not rejected**.
Its two viewport rows remain DESIGN-GAP/unmeasured/unwaived. This prerequisite
does not measure product coverage; all 382 continuation rows remain gaps until
verified PNG import and live-fixture wiring in PR #68.

## Approval and execution sequence

1. Owner posts the exact new bundle integrity line on this prerequisite PR.
   Codex reads it back and binds the comment ID; hosted CI must then pass.
2. Owner merges the prerequisite from Terminal. Codex never merges.
3. After merge verification, owner dispatches the existing workflow with
   `reference=s18-v32108` and immutable source commit
   `132fedbbd1bcc5a22c3d7d0281499c77d029df33` (the verified design-ingestion merge).
4. Codex verifies the downloaded run archive and every PNG against the manifest,
   then stages import and measurement in PR #68. The resulting bundle including
   PNG digests requires a fresh owner integrity comment; no calibration run is
   itself permission to import or approve exceptions.
5. Measure 18 default-flow rows and retain the two manual gaps. Disclose actual
   geometry/content differences and propose exact-image exceptions only after
   hosted measurement. Independent Claude QA follows fully green CI and must
   probe version-conflict reload UX and rapid-toggle races.

## Local validation limitations

The capture browser regression runs on macOS, writes no baseline images, and is
not a hosted conformance result. It verifies all 18 source state/viewport cases
with three fresh-context samples each, plus the reviewer-only radius change.
The production calibration entry point still rejects non-hosted pins. There is
no claim of product parity, live-backend QA, or measured S-18 coverage here.
