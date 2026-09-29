# S-18 implementation — initial draft

Scope: `/s-18`, Notifications and appearance, consuming the existing
`GET/PATCH /api/v1/student/settings` contract. No backend, S-19 product,
reference, tolerance, enforcement, or historical-evidence changes.

Design authority: v3.2.1.08 canonical ZIP, SHA-256
`0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964`.
Base: ingestion merge `132fedbbd1bcc5a22c3d7d0281499c77d029df33`.

## Implemented

- S-18-scoped mobile/desktop composition, one main with sibling desktop aside,
  48px controls, labelled notification switches and collapsed appearance panel.
- Save-on-change with a dirty pending draft separate from confirmed server values.
  Only validated server responses announce Saved and advance the version.
- Session-gated initial read; loading, loaded, saving, saved, validation,
  version-conflict, network, forbidden and session presentations.
- Synchronous duplicate-write lock; route-owned completion; query/hash changes
  do not release the transport lock early or leave the UI stuck busy.
- Failure rollback and explicit retry; conflict requires reloading current values.
- Dark stores a preference only; no dark visuals. Hindi remains unavailable in
  accordance with the capability disclosure. No fabricated user identity.

## Local validation (not hosted conformance or independent QA)

- Frontend matrix: 2,500 passed; one pre-existing skipped test; 161 files passed.
- Typecheck and lint pass; production build passes.
- Standalone synthetic-API Chromium suite: 11/11 pass, including versioning,
  double activation, rollback/retry, conflict reload, HTTP 401/403/422, theme,
  query/hash settlement, 320/390/1440 reflow, 48px targets and axe serious/critical.
- New unit/SSR tests were added before the implementation; the nested button
  icon regression was separately observed RED before its wrapper correction.
- Run the browser suite from `frontend`:
  `node --test scripts/lib/nyay88-settings.browser-contract.mjs`.
  It requires the repository's installed Playwright Chromium. It is kept out of
  the Node-only unit matrix; hosted wiring is pending approved test alignment.
- No live-backend, physical-device or independent-Claude claim is made here.

## Owner decisions and sealed alignment — 29 Sep 2026

Save-on-change is approved as the shipped default. Optional manual Save/Discard
(Option B) is **deferred pending user feedback — not rejected**. Its two viewport
rows remain DESIGN-GAP, unmeasured and not waived. The measurement target is the
18 default-flow rows (nine states at two viewports), not a claim of 20 passes.

The approved test-only alignment adds S-18 to the Revision L heading/logo census,
uses its exact heading and three switch roles in the sealed browser producer,
and moves the legacy negative control to unchanged S-19. Namespace inventory
increases from 170 to 174 production inputs and the existing mark from 10 to 11
uses. Backend/versioning assertions, product code, references, tolerances and
enforcement settings are unchanged by this alignment.

Regression evidence: the new census expectations failed before alignment
(three failures); the heading/switch producer contract separately failed before
alignment (one failure). Updated suites pass. Chromium census 22/22 and S-18
synthetic-API browser checks 11/11 pass. These are not hosted visual results.

The existing owner-only calibration workflow currently accepts only `r2` and
`revl`. Continuation reference generation needs a narrow trusted calibration
extension, a fresh owner integrity approval, an owner merge and owner dispatch,
then verified PNG import. Reference generation must not run inside PR capture.
No local diagnostic image is promoted to an approved baseline.

## Required before Testing

1. Hosted validation of the approved sealed expectation/inventory alignment.
2. Add narrowly scoped hosted S-18 fixture/capture/coverage support. PR #67
   imported design-source coverage, not S-18 PNG references. The current gate
   does not yet measure S-18: all 20 S-18 rows remain DESIGN-GAP. Existing 74
   blocking rows and all 382 continuation rows/configuration are unchanged.
   Protected bundle edits need a fresh owner integrity approval. Baseline
   generation remains owner-dispatched; no local diagnostic becomes a baseline.
3. Preserve the approved manual-mode deferral: its two rows remain unmeasured.
4. Hosted measured comparison of stable/fixture states; any intentional content
   differences require fresh exact-image owner exception approval, not a blanket
   waiver. The synthetic local fixtures are not reference approval evidence.
5. Full green hosted CI and independent Claude handoff with six-file evidence,
   including self-contained preview.svg. Keep implementation In Progress until
   the real gate verdict is available; do not mark Testing from these local checks.
