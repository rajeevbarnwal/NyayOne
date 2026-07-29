# Option C2 reference v1 — LegalSaathi Wave 2 tutoring (S-31…S-35)

Executable, measured design reference for the approved Option C2 direction.
Owning tickets: **SAATHI-125** (S-31…S-34) and **SAATHI-129** (S-35).

Start with `SOURCE_OF_TRUTH.md`.

| File | What it is |
|---|---|
| `SOURCE_OF_TRUTH.md` | provenance, what is approved, what is proposed, what is pending |
| `PRODUCT_DECISION_REGISTER.md` | 18 decisions traced to live Jira comments, or marked absent |
| `STATE_INVENTORY.json` | all 82 states, 13 attributes each |
| `SCREEN_ROUTE_API_BINDING_MATRIX.md` | screens, routes, obligations — no invented API names |
| `DETERMINISTIC_FIXTURE_CONTRACT.json` | frozen fixtures + checksum + privacy canaries |
| `RESPONSIVE_GEOMETRY_BUDGETS.md` | budgets and the 1,968 measured rows behind them |
| `ACCESSIBILITY_AND_INTERACTION_SPEC.md` | targets, focus, announcements, non-colour cues |
| `TOKEN_COMPONENT_MOTION_SPEC.md` | tokens, components, motion, the live-room repair rules |
| `IMPLEMENTATION_HANDOFF.md` | what to rely on, what not to, and how to reproduce |
| `VISUAL_BASELINE_MANIFEST.json` | 40 reference captures with per-file SHA-256 |
| `MEASURED_GEOMETRY_RESULTS.json` | 1,968 real Chromium rows |
| `BEFORE_AFTER_LIVE_ROOM.json` | the reproduced defect, its root cause and the repair |
| `NEGATIVE_TEST_RESULTS.md` / `.json` | 81 executable negative cases |
| `NATIVE_GATE_RESULTS.json` | frontend gate return codes for this branch |
| `reference/` | the offline executable reference (open `index.html`) |
| `tests/`, `tools/` | the executable equality test and the measurement/checksum tools |
| `sources/` | read-only copies of every upstream source used |
| `captures/` | the reference PNGs |
| `SHA256SUMS.txt` | checksums of every file above |

Open `reference/index.html?state=s35-room-live&chrome=1` to browse all 82 states.
Fully offline: no network request, no cookie, no web storage.

## S-35 live-room geometry closure addendum

Contract: `QA/wave2_priority1_design_reference_closure_2026-07-29/S35_LIVE_ROOM_GEOMETRY_CLOSURE_ADDENDUM.md`
(SAATHI-129 comment 12935).

The addendum named six root causes in the approved Option C2 source
(`docs/design/tutoring_option_c2_mobile_gate_2026-07-29/C2_MOBILE_GATE.html`). All six are
corrected in this reference package. Option C2 art direction, S-31, S-33, S-34, the S-35
refund journey, typography, colour tokens and copy are unchanged.

| # | Root cause in the approved source | Correction in this package |
|---|---|---|
| RC-1 | `.live{height:100dvh;height:100vh}` — the later `100vh` wins and defeats dvh | `.live-host{height:100vh;height:100dvh}` — the fallback is declared **first**, so `100dvh` wins |
| RC-2 | the rig `.app` used only `min-height:100%`, so viewport units measured the outer browser | complete chain `html -> body -> #app -> .live-host -> .live`, plus `.vp[data-screen="s35live"\|"s35land"] > .app{height:100%;min-height:0;overflow:hidden}` for the offline device rig (`?rig=vp&device=WxH`) |
| RC-3 | `.lctrl` permitted `flex-wrap:wrap`, so the dock could become multiple rows | `.lctrl{flex:0 0 auto;flex-wrap:nowrap}` |
| RC-4 | inline 40x40 minimums on session-details and sheet-close | removed; `.live button,.live [role="button"]{min-width:44px;min-height:44px}` is the floor |
| RC-5 | 30x30 self-view controls and a 78x58 landscape self-view | controls moved **inside** the self-view; portrait 112x140 and landscape 116x100 contain two 44x44 targets without overlap; the minimised tile hides `.selfmove`, the tile `>svg` and `.nm2`, leaving exactly **one** 44x44 restore control |
| RC-6 | no explicit positioned, constrained three-row layout | `.live{position:relative;height:100%;min-height:0;overflow:hidden;display:grid;grid-template-rows:auto minmax(0,1fr) auto}` with `.stage{min-width:0;min-height:0;overflow:hidden}` |

Documented exception: below a 361 px viewport the dock still wraps. That is the WCAG 2.2
1.4.10 reflow path for 200 % zoom (the 195x422 case), and it drops no control. Every
viewport in the mandatory matrix is >= 390 px wide and never wraps.

### Readiness

The live room advertises `data-live-room-ready="true"` on the live root, and only after the
fixture checksum matches, `document.fonts.ready` has resolved, every required media tile and
the control dock are mounted, and the DOM has been mutation-quiet for a full animation frame.
The markup ships `data-live-room-ready="false"`. There are no fixed sleeps in any harness.

### Executable acceptance matrix

`node tools/measure_live_room_addendum.mjs` — 6 viewports (390x844, 430x932, 768x1024,
844x390, 932x430, 1024x768) x 2 themes = 12 pairs, each asserting all 12 addendum rules from
real Chromium rectangles, plus rules 1-6 re-asserted for six states (camera-denied,
mic-denied, disconnected/reconnecting, provider-failure, leave-confirmation, device-release).

Results: `LIVE_ROOM_ADDENDUM_RESULTS.json` (12/12 pairs, 72/72 state rows) and
`BEFORE_AFTER_LIVE_ROOM_ADDENDUM.json` (before/after rectangles per pair).
Captures: `captures/addendum/`.
