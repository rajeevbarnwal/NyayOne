# Option C+ Guided Confidence — Closure Report (correction cycle, F1–F4)

**Folder:** `lawschool_s27_s30_option_c_plus_corrections_2026-07-27/` (new versioned sibling — the reviewed package was not overwritten). **No production frontend/backend code was touched; Jira was not accessed or transitioned.**

**Reconstruction caveat (stated up front):** the reviewed local package and review file paths are not reachable from this design environment. The corrected artifact was **rebuilt from the approved Option C source + the frozen Product decisions + the independent review's descriptions**. All frozen decisions are implemented (verified statically below); any *visual* micro-deltas versus the local C+ file should get a quick Product eyeball. The 12-school sample seed here yields **6** differing facts for the nlsiu+nalsar fixture (the reviewed package's seed yielded 8 of 11) — the harness computes the expected count from the shipped seed rather than hard-coding it.

## F1–F4 → changed files and evidence

| Finding | Fix (file: `OPTION_C_PLUS_GUIDED_CONFIDENCE.html` unless noted) | Executable evidence |
|---|---|---|
| **F1 · route scroll/focus** | Deterministic hash-route manager: `routeStack` + `scrollMem`; forward navigation → `scrollTo(0,0)` + `focusHeading()` (destination `h1`/panel heading, `tabindex="-1"`, `focus({preventScroll:true})`, no `aria-live` on headings → no double announcement). Browser Back pops the stack and **restores the prior scroll position**. Same-route re-renders never steal focus. | Harness **F1 ×3**: S-27@scrollY 400 → S-28, S-28 → S-29, S-28 → S-30; asserts `scrollY===0` **and** `document.activeElement === destination heading`. |
| **F2 · chip semantics** | `chp()` renders the ✓ glyph **only when selected**, wrapped `aria-hidden="true"`; `aria-pressed` is the only state carrier. Same pattern applied to Save/Follow/Compare glyphs (★/✓ all `aria-hidden`). | Harness **F2 ×3**: exact accessible names — unselected "South" (no ✓, pressed=false), selected "Anywhere" (glyph hidden, pressed=true), post-click "South" (pressed=true, name unchanged). |
| **F3 · tray obstruction** | Pick tray → **in-flow `position:sticky; top:0`** band (occupies layout space; content can always scroll clear); `html{scroll-padding-top:92px; scroll-padding-bottom:110px}`; global `focusin` guard scrolls any focused element out from under the tray **and** the bottom tab bar; **Reviewer button moved into the header (in-flow, static)**; **baseline mode** (`&baseline=1` in the hash query, or `body[data-baseline="1"]`, or Reviewer → "Enable baseline mode") hides all reviewer tooling for screenshots. | Harness **F3 ×4**: computed `position:sticky`; reviewer button in `<header>`; baseline hides it; 8-target focus walk at true 390×844 asserts zero rect intersection with tray/tab bar. |
| **F4 · native evidence** | `CAPTURE_MANIFEST.json`: **40 native-viewport entries** (S-27/28/29/30 × 390×844, 430×932, 768×1024, 1024×768, 1440×900 × light/dark) each recording route/state/theme/viewport/DPR/sha256/console/scroll-width/min-target fields + a Playwright recipe + the baseline-mode and raster-dimension rules. Reviewer frame presets are labelled **design-preview-only** in the drawer and manifest. QA documents reconciled — this report states exactly what ran where. | Entries are `pending_native_rig` — see Verdict. |
| **Copy** | Follow copy is exactly: *"Following marks a school for future verified updates. Prototype: no notifications are sent."* (S-28 helper, S-30 intro, follow announcement). Old queue-implying copy removed (static scan: 0 occurrences). | Static scan pass. |

## Frozen decisions — implementation check (static, executed)
Forest/terracotta/indigo/teal/amber palette ✓ (indigo = comparison treatment) · monograms, no logos ✓ · "Differences only" **off by default** ✓ (`diffOnly:false`, harness-asserted) · three-column S-27 at **≥1360px** ✓ (`@media(min-width:1360px)`) · guided three-step header **S-27 only** ✓ · catalogue **12** vs **config-driven compare max (default 4)** kept distinct ✓ (`CONFIG={compareMax:4,…}`; copy "CATALOGUE 12 · LIMIT (CONFIG) 4").

## Required gates — execution ledger

| Gate | Status | Where executed |
|---|---|---|
| All 48 states render | **Executable in harness** (walks all 48) · static: 48/48 IDs in artifact | harness check 2 |
| Zero console/page errors | Executable in harness (error + console.error hooks across every check) | harness final row |
| Zero horizontal overflow at true viewports | Executable in harness — **40 true-iframe measurements** (5 viewports × 2 themes × 4 screens) | harness overflow row |
| Targets ≥44×44 | Executable in harness (min-rect walk @390) · static CSS audit pass | harness touch row |
| No fixed/sticky obscures actionable/focused | Executable in harness (F3 rows) | harness F3 |
| Route scroll/focus | Executable in harness (F1 ×3) | harness F1 |
| Exact accessible names | Executable in harness (F2 ×3) | harness F2 |
| Differences-only fixture + default off | Executable in harness (11 → 6 computed from shipped seed) | harness S-29 rows |
| Light/dark WCAG AA | **Executed here** — 28 pairs computed, all ≥5.15:1 (token spec table) | this package |
| Package checksums | **Executed here** — `SHA256SUMS.txt` | this package |

## Verdict — **BLOCKED** (no fabricated PASS)
Two exact external blockers, everything else delivered:
1. **Platform preview outage** (unchanged this session; my pane, the user-view pane and pixel capture all time out on a bare `1+1`) — so the harness could not be *run by me*. It is shipped and runs in ~1 minute on any served Chromium: `python3 -m http.server 8080` → open `QA_HARNESS_C_PLUS.html` → **Run all checks** → **Download JSON report** (drop it in this folder as `QA_C_PLUS_EXECUTED_RESULTS.json`).
2. **Native-viewport captures** physically require a real browser window/Playwright (`CAPTURE_MANIFEST.json` carries the recipe); no environment here can set a true 390×844 browser viewport.

When (1) and (2) run green on your rig, this package meets every gate → **PASS — ready for independent QA and Product baseline approval.**
