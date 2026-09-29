# S-18 reference import and measured-capture candidate

This is a candidate update for PR #68, not an approval, hosted S-18 conformance
result, enforcement promotion or independent QA handoff.

## Owner calibration provenance

- Run: <https://github.com/rajeevbarnwal/NyayOne/actions/runs/36565721312>
- Result: successful, first attempt; actor and triggering actor both
  `rajeevbarnwal`; `workflow_dispatch` on `main`.
- Control/main: `33d7851cfddd30139066b708b3e8db9ddc8733b2` (PR #69 merged).
- Frozen source: `132fedbbd1bcc5a22c3d7d0281499c77d029df33` (PR #67 merged).
- Artifact ID: `11031931648`.
- Downloaded ZIP SHA-256, independently recomputed and matched to GitHub:
  `9a2c048287bc281a61868347effe829cf2a2a4b355ffdde7a1bcaa23ca758567`.
- Manifest SHA-256:
  `38aa36b79f8dc7cc9bbdbdbc9b1ce26626f34a52cc253f3e317d59a9ff2ba5e9`.
- Canonical design ZIP SHA-256 remains
  `0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964`.
- 20/20 checksum entries verified: 18 PNGs, manifest and runtime pins.
  Every PNG has the expected dimensions and three byte-identical samples.
- Pins: Chromium `149.0.7827.55`, Playwright `1.61.1`, `linux-x64`, Node
  `v22.21.1`, existing approved font bytes. The source ZIP/member hashes and
  embedded font/logo inventory also verify.

The complete per-PNG digests are in
`frontend/test-baselines/nyay66/s18-v32108-chromium-149.0.7827.55-36565721312/SHA256SUMS`.
The importer recomputes the ZIP digest itself, reads only an exact member
inventory without filesystem extraction, verifies every checksum/PNG, and
refuses output overwrite. The loader revalidates manifest, provenance, pins
and every PNG at use. The fresh owner integrity approval binds these files.

## Explicit coverage semantics

Nine states × mobile390/desktop = 18 reference rows. The live producer uses
the real application route with synthetic API projections for loading, loaded,
saving, saved, invalid, conflict, network and forbidden (16 rows). Pending GET
and PATCH responses are deliberately held by the test transport; no production
delay or navigation freeze is added. The validation rejection is a synthetic
422 response to a valid switch action, not proof of a real backend rejection.

The real typed `401 authentication_required` response invokes the existing
auth guard and redirects S-18 to S-03. The owner approved component + route
evidence in this task, recorded as `NYAY-88:16029`. The two session-error rows
render the actual `NotificationsSettingsView` through a separate test-only
entry and also execute the genuine 401 live-route redirect check. Reports
label these rows `component-visual`. Missing redirect proof, wrong destination,
unapproved coverage reference, artificial delay or navigation freeze fails
closed. The normal product build emits no fixture route. The existing isolated
CI build invokes the separate fixture builder; its original S-01 output remains
in its original directory, while S-18 uses a separate output directory.

The two `option-manual` rows remain DESIGN-GAP/unmeasured, deferred pending
user feedback — not rejected or waived. With all 18 captures measured, 364
continuation gaps remain (two S-18 optional rows plus 362 later-screen rows).
Missing/duplicate measured-row inventory fails closed instead of silently
backfilling gaps. Failed captures block; visual deltas remain NONCONFORMANT
until genuine measurements and fresh exact-image owner exceptions resolve them.
The new rows are measurement/report-only at this stage; no S-18 enforcement
promotion is claimed. All 74 existing rows remain blocking.

## Protected-bundle disclosure

- Add 18 PNGs, calibration manifest/runtime pins/checksums/provenance and the
  `s18` cache binding in policy.
- Add hash-verifying import/load support and regression tests.
- Add S-18 live fixtures, exact negative-response diagnostic classification,
  component-only session entry, and real-Chromium rehearsal tests.
- Extend the existing test-only fixture builder with a separate S-18 output.
- Add S-18 capture/comparison and coverage reporting; require the owner-approved
  session component+route proof and exact 18-row inventory.
- Extend exception eligibility only to measured S-18 coverage, using the existing
  exact-image hash / owner PR-comment mechanism. No exceptions are added yet.

No product source, auth/route behavior, backend code, existing reference PNGs,
canonical design ZIP, fonts, tolerances, existing 74-row enforcement list or
existing exception entries are changed by this import/capture step. No workflow
permissions, container mounts, credentials, triggers or seals are changed.

## Validation and next step

Tests-first import and additive coverage regressions were RED before support
and GREEN afterward. Local production-build rehearsal covers all 18 rows plus
the complete measurement producer; it is macOS diagnostic evidence, not hosted
pixel parity and not an exact-image exception approval. Automated axe checks
found zero serious/critical violations in these local fixtures.

Post the fresh `NYAY66-INTEGRITY` line on PR #68, then read back/bind its owner
comment ID. Only afterward can the hosted trusted reader accept this bundle
and produce exact-head S-18 verdicts. Publish any real geometry fixes or scoped
exception proposals from that hosted evidence, then complete CI and independent
Claude QA, including conflict-reload UX and rapid-toggle races. Owner merges.
