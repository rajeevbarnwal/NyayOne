# S-20 capture-only calibration prerequisite

Owner approved this separate support PR on 2026-10-18. It is not the S-20
implementation, a reference import, an enforcement promotion, or a QA pass.
The implementation remains in PR #72.

## Exact scope

- Add `s20-v32108` to the existing manual-only calibration workflow.
- Render the frozen v3.2.1.08 S-20 source: ten design states at mobile390
  (390 × 844) and desktop (1440 × 1024), three fresh-context samples per row.
- States: loading, results, filters-open, verified-empty, empty, partial,
  save-failed, error, offline, local-empty. All 20 rows remain DESIGN-GAP here.
- Verify the canonical archive, all member hashes, HTML, embedded resources and
  state inventory before rendering. Archive SHA-256:
  `0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964`.
- Retain Chromium 149.0.7827.55, Playwright 1.61.1, linux-x64 and exact font pins.
- Use trusted workflow-control capture code, not candidate scripts. Refuse
  external requests. Normalize only the reviewer viewport radius, never app
  styling, geometry, text or controls. Capture full declared viewports without
  shrinking below-fold content.
- Require 3/3 byte-identical samples. Record source/control heads, runtime/font
  pins, dimensions, surface metadata and SHA-256 checksums.
- Publish unimported artifacts only. Both actor and triggering actor must be
  the owner; dispatch must be on main. Retain read-only permissions, immutable
  action pins, no persisted credentials and 14-day calibration retention.

## Integrity disclosure

New protected capture-support files:

- `frontend/scripts/nyay66-s20-calibrate.mjs`
- `frontend/scripts/lib/nyay66-s20-reference.mjs`
- `frontend/scripts/lib/nyay66-s20-reference.test.mjs`
- `frontend/scripts/lib/nyay66-s20-capture.mjs`
- `frontend/scripts/lib/nyay66-s20-capture.browser-contract.mjs`

The only edits to existing protected files are the workflow SHA-256 constants
in `nyay66-s18-reference.mjs` and `nyay66-s19-reference.mjs`. Their capture/import
behavior is unchanged. The new exact workflow seal is
`2afb10d2f467dda9480c3855afb2dc95edab64134caeca72b359c29c5d1f5b34`.

Outside the protected bundle: the workflow's choice/validation/dispatch branch,
its CI-policy seal, workflow regression tests and this record.

Product code, evaluator, policy (including exceptions/enforcement/tolerances),
font assets, canonical sources and existing PNG references are byte-unchanged
from main `a25ede7413d3ef4a9c61ab958f8f4f10c05e60a0`. Existing 142 measured rows
(74 original + 18 S-18 + 50 S-19) retain their coverage and blocking controls.
The optional manual-save rows remain unmeasured; no coverage is promoted here.

## Validation

- RED: workflow tests failed for the absent S-20 choice/control branch; S-20
  reference test failed to load its not-yet-implemented module.
- GREEN: 18 S-18/S-19/S-20 reference tests; 96 workflow/policy/trust regressions.
- Full frontend suite: 2,670 passed. Typecheck, lint and build passed (existing
  bundle-size warning only). Namespace gate and all 21 namespace tests passed.
- Local browser regression: 21/21 passed, covering 20 rows with three identical
  fresh-context captures each, plus reviewer-radius-only isolation. This is a
  macOS diagnostic rehearsal, not Linux-hosted calibration. No PNG was imported.
- CI workflow policy: all 14 workflows passed.

## Owner-operated sequence

1. Owner posts the fresh top-level `NYAY66-INTEGRITY <digest>` approval on this
   prerequisite PR. Codex reads it back and binds the owner comment ID.
2. Hosted validation and review clear; owner marks Ready and merges exact head.
3. Codex supplies the exact `s20-v32108` owner-dispatch command after merge.
4. Owner dispatches. Codex verifies the resulting 20 PNGs and artifact manifest.
5. Import into PR #72 requires another integrity approval covering PNG digests.
   Hosted product measurement, genuine defect corrections, scoped exception
   approvals and independent Senior QA follow separately.

No self-approval, dispatch, merge, reference import or product promotion occurs
in this prerequisite.
