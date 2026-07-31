# Option C2 reference v1 — Source of truth

**Package:** `docs/design/tutoring/option_c2_reference_v1`
**Owning tickets:** SAATHI-125 (S-31, S-32, S-33, S-34) and SAATHI-129 (S-35)
**Parents:** SAATHI-65 (S-31–S-34) and SAATHI-66 (S-35)
**Role:** Senior Engineer — Wave 2 Priority 1 design-reference closure
**Date:** 2026-07-29

Every claim in this package carries exactly one label:
`PRODUCT_APPROVED` · `BROWSER_MEASURED` · `PROPOSED` · `PENDING_PRIORITY2_CONTRACT` · `OUT_OF_SCOPE`.

---

## 1. What this package is

`PRODUCT_APPROVED` — Option C2 is the approved Wave 2 tutoring visual direction for S-31–S-34
(SAATHI-125 comment 12927) and for S-35 (SAATHI-129 comment 12928).

This package is the **executable, measured reference** for that direction. It is a design and
geometry reference only. It does not ship, does not touch the production frontend, and does not
by itself qualify any ticket for Testing. Implemented-code and target-runtime QA remain separate
gates on the parents.

## 2. Upstream sources and their status

| Source | Status | Used for |
|---|---|---|
| `docs/design/Payments_Refunds_Design/tutoring_payment_refund_options_2026-07-29/STATE_INVENTORY.md` | `PRODUCT_APPROVED` | The 82 named states. Copied verbatim to `sources/STATE_INVENTORY_SOURCE.md` and asserted by an executable set-equality test. |
| `docs/design/tutoring_option_c2_wow_art_direction_2026-07-29` | `PRODUCT_APPROVED` | Approved art direction (C2 Legal Studio): colour ramps, typography, materials. |
| `docs/design/tutoring_option_c2_mobile_gate_2026-07-29/C2_MOBILE_GATE.html` | `PRODUCT_APPROVED` (frames) / defective (live room) | S-31, S-33, S-34 and S-35 refund compositions and tokens, copied and adapted. Latin font subsets extracted verbatim. |
| `docs/design/Payments_Refunds_Design/tutoring_payment_refund_option_c_human_icons_2026-07-29` | historical | Structural source for the new S-32 frame (see §4). |
| `QA/wave2_tutoring_design_2026-07-29/OPTION_C2_MOBILE_GATE_INDEPENDENT_PRODUCT_UX_REVIEW.md` | binding review | The live-room correction mandate. Copied to `sources/`. |
| `tutoring_option_c2_mobile_gate_2026-07-29/MOBILE_GEOMETRY_RESULTS.json` | `pending_measured_run` | Superseded **inside this package only** by `MEASURED_GEOMETRY_RESULTS.json`. The historical file is untouched in its own package and copied here read-only for provenance. |

**No historical package was modified, staged or deleted.** All sources were read from the user's
working checkout read-only and copied into `sources/`.

## 3. What was frozen unchanged

`PRODUCT_APPROVED` — the independent review froze S-31 marketplace, S-33 payment/hold, S-34
confirmation and S-35 refund as reference compositions. Their structure, hierarchy, copy intent
and token usage are carried over. Changes to those four families in this package are limited to:

- reflow rules at <=360 CSS px and long-string wrapping (no content or hierarchy change);
- an exact, measured sticky-dock reservation so the dock can never bury the final content;
- `inert` on the background while a modal is open (an accessibility correction, not a redesign);
- a fade affordance on the S-31 practice-area rail, which the review explicitly requested as a
  non-blocking refinement.

## 4. What is new and needs Product sign-off

`PROPOSED` — **the S-32 tutor-profile family.** The approved C2 mobile-gate package contains no
S-32 frame, but S-32 is owned by SAATHI-125 and two S-32 states exist in the approved 82-state
inventory. This package therefore adds an S-32 frame as a **controlled adaptation**: the
information structure is taken from the approved Option C S-32 frame (identity header, fee and
duration, bio, verification and language chips, timezone-labelled availability list with
available/held/booked, "what happens next" education, server-authority note) and is restyled with
approved C2 tokens and components only. No new token, colour or component was invented.

Product must confirm this adaptation. Until then S-32 is `PROPOSED`, not `PRODUCT_APPROVED`.

`PROPOSED` — the live-room repair (§5), the pre-join/device family composition, and every typed
error label. Typed error labels are UI obligations only; see §6.

## 5. The blocking defect and its repair

`BROWSER_MEASURED` — reproduced in real headless Chromium against the historical package.
Full detail and root cause: `BEFORE_AFTER_LIVE_ROOM.json`.

| Frame | Viewport | Before (historical) | After (this package) |
|---|---|---:|---:|
| S-35 live portrait | 390x844 | 308 px unwanted scroll, 40 px min target | **0 px, 44 px** |
| S-35 live portrait | 430x932 | 308 px, 40 px | **0 px, 44 px** |
| S-35 live landscape | 844x390 | 281 px, 40 px | **0 px, 44 px** |
| S-35 live landscape | 932x430 | 290 px, 40 px | **0 px, 44 px** |

The independent review reported 309/309/621/581 px from its own browser session; the direction and
magnitude are confirmed, and the exact landscape figures differ because the historical harness
measures a nested device bezel whose height depends on the outer window.

**Root cause:** the details sheet was `position:absolute` with its containing block on `.app`, not
`.live`. `.live{overflow:hidden}` therefore never clipped it, so a sheet translated by
`translateY(100%)` added exactly its own height to the document scroll height.

**Repair:** the room root is exactly `100dvh` with `grid-template-columns:minmax(0,1fr)` and
`grid-template-rows:auto minmax(0,1fr) auto`; page scroll is disabled on that route; the sheet is
`position:fixed` so it cannot contribute to document height; every room control is >=44x44;
landscape compacts the header and self-view but never removes a control.

Only the live-room composition was changed. S-31, S-33, S-34 and the refund compositions were not
redesigned.

## 6. What this package deliberately does not decide

`PENDING_PRIORITY2_CONTRACT`

- **W2-6 attendance and completion authority** (SAATHI-65 comment 12800, SAATHI-129 comment 12805).
  Attendance states show the UI obligation and typed refusals as *labels*. They are not an API.
- **W2-9 video-provider seam** (same comments). Pre-join, room and reconnect states show the UI
  obligation only. No provider, SDK, transport or event name is asserted anywhere.
- **All typed error identifiers** in this package that are not present verbatim in an approved
  source are marked `(PROPOSED label)` in `STATE_INVENTORY.json`. `HOLD_EXPIRED` and
  `DUPLICATE_SUBMIT` come from the approved Option C frames; everything else is proposed.

`OUT_OF_SCOPE` — production frontend code, backend contracts, real payment or video integration,
and any lifecycle transition of SAATHI-65 or SAATHI-66.

## 7. How to verify this package

```
node docs/design/tutoring/option_c2_reference_v1/tests/state_inventory_equality.test.mjs
node docs/design/tutoring/option_c2_reference_v1/tools/measure.mjs           # real Chromium
node docs/design/tutoring/option_c2_reference_v1/tools/run_negative_matrix.mjs
node docs/design/tutoring/option_c2_reference_v1/tools/gen_checksums.mjs
open docs/design/tutoring/option_c2_reference_v1/reference/index.html?state=s35-room-live&chrome=1
```

The reference is fully offline: no network request, no web storage, no cookie, no external font.
