# v3.2.1.08 light continuation intake

Owner approved the canonical design on 29 September 2026 (NYAY-90, approval
record 16011). Release epic v3.2.2 uses design version v3.2.1.08; these are
different version labels, not a source mismatch.

Canonical release ZIP (6,301,227 bytes):
`frontend/test-baselines/nyay66/v3.2.1.08/NYAYONE_S01_S35_v3.2.1.08.zip`

SHA-256: `0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964`.
This is byte-identical to the owner-approved local
`docs/design/v3.2.2/v3.2.1.08/NYAYONE_S01_S35_v3.2.1.08.zip`.
Its protected cache location ensures the existing trusted reader exports and
integrity-binds the archive. The 249.70 MB workspace export is not imported.
The canonical HTML, manifest, provenance, build inputs and source are retained
inside the release ZIP. No historical file or old reference PNG is replaced.

## What this changes

- 15 approved source IDs: S-18–S-21 and S-25–S-35; 191 documented states.
- 382 light DESIGN-GAP rows = 191 states × existing mobile390/desktop pair.
- These rows explicitly have `executed:false`, `measured:false`,
  `designApproved:true` and no pixel/PNG proof. DESIGN-GAP here is a measurement
  gap, not a claim that owner design approval is missing. They are not passes.
- The existing finalizer runs unchanged before additive source rows are appended.
  Its failures, blocking result and 74 required light rows are preserved.
  36 existing dark gaps remain unchanged (418 total gaps; 492 total report rows).
- Source-only font inventory: Public Sans, Space Grotesk, Carlito fallback,
  Spectral wordmark, Spline Sans Mono; 51 embedded font-face declarations and four
  SVG definitions hash-bound to the frozen continuation. Definitions are not a
  rendered-font census. No product font/logo-use counter is prematurely changed.
- Runtime validates the archive SHA before reading its members, verifies all 22
  shipped hashes, compares the state matrix and font/logo digests with the actual
  source, and never executes shipped design helpers.

No product code, fixture authority, tolerance, exception, measured reference,
enforced-screen list, runtime font, workflow trigger or historical evidence changes.
This is not PNG calibration. Owner-dispatched pinned hosted calibration and fresh
owner integrity approval are still required for future raster imports. Individual
screen PRs add approved fixtures and promote actual measured coverage. Optional or
unbacked prototype states must be explicitly dispositioned, never invented as API
successes or counted as passing. 320px reflow remains an implementation/QA criterion.

## Accepted qualifications

- dark mode deferred
- S-22–S-24 reserved under NYAY-89
- live backend/payment/video flows untested
- 210 axe incomplete checks pending manual review (the review precisely reports
  **210 scans** with incomplete/manual contrast items, not 210 known violations)
- mobile-density refinements optional

Delete-review disclosure quoted verbatim from REVIEW_v3.2.1.08.md:

> Pending/published neutral failure, Keep, delete and duplicate refusal freshly verified. Delete is a prototype proposal; static rating display is not aggregate mutation proof.

> Destructive-confirmation initial focus remains on Delete (Keep-first is still an advisory preference, not a new blocker).

Owner approval covers that disclosed proposal; it is not proof of live deletion.
The inherited iframe extra-Back behavior is viewer-only informational, not product
debt and not NYAY-84. Frozen HTML's original pending-approval labels remain intact;
the external owner approval record supersedes their historical status.

## Merge boundary

The protected bundle changes. A fresh exact `NYAY66-INTEGRITY <digest>` comment
from the owner on the ingestion PR must be read back and bound before hosted gate
validation. Codex does not self-approve, merge, or dispatch calibration.
