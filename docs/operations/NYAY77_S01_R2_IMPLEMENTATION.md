# NYAY-77 — S-01 light R2 implementation (Draft)

Base: PR #39 merge `6ee7e1b117eea33438bf10fd0cf48263ddb895fe`.
Reference approval: NYAY-50 comment 15422. NYAY-50 closure: 15446.

## Delivered in this screen branch

- R2 checking lockup, indeterminate progress, neutral failure copy, manual keyboard-accessible retry, and authenticated resolved presentation.
- Automatic routing stays server-authoritative. Pending/unavailable never navigate. Authenticated goes to S-07; anonymous goes to S-02 unless the new boolean `nyayone.r2.onboarding-seen` preference is exactly `true`, in which case it goes to S-03. No identity/consent is stored. Old LegalSaathi markers are not migrated. The subsequent S-02 PR will write the new preference after showing onboarding; this PR only reads it.
- No timers added for decorative delay, no Continue button, no automatic retry, no change to the existing 10-second request timeout or authentication authority.
- Only S-01 presentation changed. Shared SVG components are reused unchanged. Light only; dark remains NYAY-51.

## Tests-first and validation

Initial visual-contract RED: 3 failures / 1 preservation pass. GREEN: 4/4.
R2 preference RED extension: 2 failures / 3 passes. GREEN: 5/5; legacy bootstrap suite 14/14, with two documented expectations updated (R2 SVG lockup and approved seen/unseen routing).

Full local frontend: 1,730 passed, 1 existing skip (131 files). TypeScript, lint and production build pass. Policy: 569/569; workflow verification: 14/14.
Actual production-build browser rehearsal: 6/6 (anonymous unseen, R2 seen, retired-marker ignored, authenticated, malformed-response keyboard retry, timeout without auto-retry). Synthetic server projections, not a real-backend integration claim.

## Necessary namespace inventory reconciliation

No namespace scanner rule, compatibility exception, workflow or required context changed.

- Shipped input paths: 157 → 159, adding only `S01R2.tsx` and `S01R2.css`.
- Inventory digest: `8face6ec17f864fbacea45184daba90fbdafea561a128cf2b111bdd5a132feb6` → `09c723daa48687dc4da4037c95a6dbd803151220381dc5de1d6a043542ad26de`.
- Runtime literal `nyayone-mark.svg`: 3 → 2 because S-01 now uses the existing approved inline lockup; one new `nyayone.r2.onboarding-seen` literal.
- Namespace contract SHA-256: `3eed575dbf58024ce2a662193b0c7eddd0cbae311e9e04a1a57534343aa60c17` → `27e8cba47ea94092306989e33389d410b995fba66082b2ec6019f821d9cf4fcf`.
- Namespace test SHA-256: `24b291e76ba641defc9e3ad77e646aee321adefe587a334a8d6e42476a94bdd9` → `edafec9651a1f2990aa591cad204a1589d60c7191b109ad281b08e537094bc21`.
- Verifier changes only these two dependent hash constants. All other seals untouched.

## Visual blocker — do not label Testing/PARITY yet

Local same-host diagnostics rendered the approved standalone R2 source and the production build at 390×844, 360×800 and 1440×1024 for checking and error states. These are diagnostic renders, **not** replacements for the Linux-hosted reference PNGs. No reference imported or changed.

Text, controls and geometry match in all six comparisons. Desktop passes numeric pixel tolerances. Mobile fails because the calibration captured `.vp` with reviewer bezel clipping (`border-radius:26px`), retaining dark corner pixels absent from the full-browser product canvas. Of the checking-state counted mismatches, 474/474 at 390 and 482/482 at 360 are in the 26px corner squares. Error: 474/474 and 482/484 respectively. No mask or tolerance adjustment applied. RGB mean remains part of the unchanged check.

| State | Viewport | Counted mismatch | RGB mean /255 | Structure |
| --- | --- | ---: | ---: | --- |
| checking | 390×844 | 0.1440% | 0.5605 | match |
| checking | 360×800 | 0.1674% | 0.6053 | match |
| checking | 1440×1024 | 0.00217% | 0.1949 | match |
| error | 390×844 | 0.1440% | 0.5886 | match |
| error | 360×800 | 0.1681% | 0.6367 | match |
| error | 1440×1024 | 0.00217% | 0.2070 | match |

Recommendation for owner approval: narrowly correct the calibration capture to exclude **reviewer-only corner clipping**, preserving application CSS, source bytes and numerical tolerances; owner dispatches calibration and approves the resulting exact bundle before import. Do not add a simulated phone bezel to production or silently rewrite approved PNGs.

A11y: no serious/critical violations on six diagnostic live renders; error state has no violations. Checking has the existing reference's no-H1 moderate finding (logo/status rather than a visible heading). No claim of real mobile-device keyboard testing; S-01 has no text input, but retry activation/focus still needs independent device QA.

## Coverage and independent QA still outstanding

The NYAY-66 bundle, references, tolerance settings and enforcement modes remain byte-identical to main. Existing hosted coverage is still 9 R2 entry rows measured / 33 unmeasured; no promotion is claimed. S-01 error fixtures and a truthful transient-resolved capture need to be added to the trusted capture path with a fresh owner integrity approval before S-01 enforcement. Do not introduce a product delay or disable navigation to fake the resolved state.

Before Testing: resolve corner-reference disposition, complete S-01 state fixtures/hosted parity, full CI green and exact-head evidence pack. Then independent Claude tester verifies real-backend session discovery, unavailable/timeout/retry, keyboard/screen-reader behavior, 360/390/1440 layout, reduced motion and no cross-screen regressions. Claude alone records independent pass and moves In Review; owner reviews and merges. No S-02 start before owner confirmation.
