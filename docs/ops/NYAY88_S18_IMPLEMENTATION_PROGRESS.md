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

## Required before Testing

1. Approved sealed browser expectation/inventory alignment for S-18; preserve
   assertions and move the legacy negative control to unchanged S-19.
2. Add narrowly scoped hosted S-18 fixture/capture/coverage support. PR #67
   imported design-source coverage, not S-18 PNG references. The current gate
   does not yet measure S-18: all 20 S-18 rows remain DESIGN-GAP. Existing 74
   blocking rows and all 382 continuation rows/configuration are unchanged.
   Protected bundle edits need a fresh owner integrity approval. Baseline
   generation remains owner-dispatched; no local diagnostic becomes a baseline.
3. Resolve the optional manual Save/Discard proposal. The frozen matrix labels
   it Option B, not default. It is not activated here; its two viewport rows
   remain explicitly unmeasured rather than being reported as passing.
4. Hosted measured comparison of stable/fixture states; any intentional content
   differences require fresh exact-image owner exception approval, not a blanket
   waiver. The synthetic local fixtures are not reference approval evidence.
5. Full green hosted CI and independent Claude handoff with six-file evidence,
   including self-contained preview.svg. Keep implementation In Progress until
   the real gate verdict is available; do not mark Testing from these local checks.
