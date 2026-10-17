# S-19 capture-only calibration prerequisite

Owner approved this separate support PR on 2026-10-17. It is not the S-19
implementation, a reference import, an enforcement promotion, or a QA pass.

## Exact scope

- Add `s19-v32108` to the existing manual-only calibration workflow.
- Render only the frozen v3.2.1.08 S-19 source: 26 design states at mobile390
  (390 × 844) and desktop (1440 × 1024), three independent samples per row.
- Verify canonical ZIP/HTML/member/resource hashes before rendering. Retain
  Chromium 149.0.7827.55, Playwright 1.61.1, linux-x64 and exact font pins.
- Read capture code from the workflow control checkout, not candidate scripts.
  Refuse external network requests. Remove only the reviewer viewport radius;
  never rewrite application styling, layout, text, controls, or source files.
- Require 3/3 byte-identical captures for each PNG. Record source/control heads,
  browser/font pins, decoded dimensions, surface metadata and SHA-256 manifest.
- Publish artifacts only. Owner actor AND rerun actor, main-only dispatch,
  read-only token, no persisted checkout credentials, no import/commit/merge.

All 52 S-19 rows remain DESIGN-GAP in this PR. Capturing the two optional-manual
design rows does not approve manual-save product mode or mark them measured.
Transient session/deletion-accepted evidence needs explicit coverage disposition
before the implementation can claim measurement; no navigation delay is added.

## Integrity disclosure

New protected files:

- `frontend/scripts/nyay66-s19-calibrate.mjs`
- `frontend/scripts/lib/nyay66-s19-reference.mjs`
- `frontend/scripts/lib/nyay66-s19-reference.test.mjs`
- `frontend/scripts/lib/nyay66-s19-capture.mjs`
- `frontend/scripts/lib/nyay66-s19-capture.browser-contract.mjs`

Existing protected file changed:

- `frontend/scripts/lib/nyay66-s18-reference.mjs`: only the exact workflow
  SHA-256 seal, because that same dispatch workflow now has an S-19 branch.
  No S-18 capture or import behavior changes.

Outside the bundle: workflow selection/dispatch branch, its exact CI-policy
seal, workflow regression tests and this operational record. The gate policy,
evaluator, existing raster references, exceptions, tolerances, font files, and
all 74 previously enforced light rows are byte-unchanged.

The new bundle requires a fresh top-level owner `NYAY66-INTEGRITY <digest>`
comment on this PR. Do not reuse the old approval, self-approve, or dispatch
before the owner merges the approved prerequisite.

## Validation

- RED: new S-19 reference module absent; workflow lacked the S-19 option.
- GREEN: 12 S-18/S-19 reference tests and 10 workflow contracts.
- Full frontend suite: 2,546 passed / one existing skipped test.
- Trusted approval + calibration policy suite: 50 passed.
- Local browser capture rehearsal: 53/53 passed (52 rows × three identical
  fresh-context samples, plus reviewer-frame-only correction test). This is
  macOS diagnostic execution, not Linux-hosted calibration. No local PNG is
  imported. A stale iframe-route assertion failed the first rehearsal and was
  corrected to S-19 before this successful full run.

## Owner-operated sequence

1. Owner posts the new bundle approval; Codex reads back and binds its ID.
2. Hosted CI/review clear → owner marks Ready and merges at the exact head.
3. Owner dispatches `reference=s19-v32108` with the reviewed source SHA.
4. Codex verifies artifacts and import provenance; fresh bundle approval covers
   exact imported PNG digests before product measurement on the S-19 PR.
