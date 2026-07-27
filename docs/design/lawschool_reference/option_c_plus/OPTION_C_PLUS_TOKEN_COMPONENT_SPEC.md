# Option C+ — Token & Component Spec (corrected)

Tokens are CSS custom properties on `:root[data-theme=light|dark]`. All ratios below are computed WCAG relative-luminance values for the shipped tokens — **28/28 pairs pass AA, minimum 5.15:1**.

## Colour tokens (functional palette — frozen decision)

| Token | Light | ratio* | Dark | ratio* | Role |
|---|---|---|---|---|---|
| `--bg` / `--card` / `--panel` | `#f7f5ee` / `#ffffff` / `#efece2` | — | `#131009` / `#1c1812` / `#262019` | — | page / surface / wells |
| `--ink` | `#221d14` | 15.35 | `#f2ecdf` | 16.13 | primary text |
| `--ink2` | `#4a4335` | 8.97 | `#d5cab7` | 11.72 | secondary text |
| `--mut` | `#6f6555` | 5.25–5.72 | `#a89a82` | 6.40–6.88 | labels |
| `--faint` | `#766a58` | 5.29 | `#97896f` | 5.15 | provenance lines |
| `--pri` (+`--pri-ink`, `--priq`) | `#1d5c3f` | 7.91 | `#82c4a0` | 8.71–8.99 | **forest** — primary actions, verified, saved |
| `--acc` (+ink) | `#a3430f` | 6.24 | `#e2915a` | 7.09–7.29 | **terracotta** — energy, bullets, hovers |
| `--ind` (+ink, `--indq`) | `#3a4691` | 8.52 | `#a4b0ef` | 8.44–8.64 | **indigo** — everything comparison: picks, diff badges/tints, toggle, focus ring |
| `--teal` (+`--tealq`) | `#0e5f64` | 7.40 | `#7cc7cc` | 9.17 | **teal** — Following identity |
| `--warn` / bg | `#7a5a14` / `#f6efdb` | 5.54 | `#dcb964` / `#2e2513` | 8.03 | sample/prototype, cautions |
| `--risk` / bg | `#8f2f22` / `#f8e9e5` | 6.84 | `#e69c85` / `#31201a` | 7.00 | errors, refusals |

\* text-pair ratio on its actual background (bg or card; state text on its tinted bg).

## Type (unchanged from approved C+ direction)
Newsreader 500–600 (display, 26–28px lede, 18–19px card/question titles) · Hanken Grotesk 400–800 (UI/body 13–14.5px) · IBM Plex Mono (metadata/provenance/wire 8.5–9.5px).

## Components (deltas from the reviewed package marked ►)
- **Guided step header (S-27 only):** 3 numbered steps — Where? / Budget / Pick 2–4 — done state = forest ✓ (decorative, `aria-hidden` inside a non-interactive div), current = terracotta ring; steps reflect answers + pick count live.
- **Choice chips:** 48px pill, `aria-pressed` authoritative; ► ✓ glyph rendered **only when selected** and `aria-hidden="true"` — accessible name is exactly the label in both states.
- **Pick tray (Step 3):** ► **in-flow `sticky top:0`** band on S-27 — count "n of 4", indigo progress bar, Compare CTA (enabled at config min 2), "CATALOGUE 12 · LIMIT (CONFIG) 4" metaline. Never overlays content; `scroll-padding` + `focusin` guard protect focused elements against tray and tab bar.
- **Monograms:** 2-letter serif initials, forest tint block (44px cards / 56px S-28); no third-party logos.
- **School card:** monogram + serif name, plain-language fact bullets (terracotta dots), evidence-led "Matches: …" chip (forest, built only from the user's own answers), Verified + Sample chips, Compare/Save actions (Compare selected = indigo), per-card provenance line.
- **S-29 comparison:** stacked per-fact attribute cards (no horizontal scroll); ► differ state = **indigo** border/tint + "values differ" badge; "same for all" metaline otherwise; ► "Differences only" `.tgl` switch — **off by default**, `aria-pressed`, indigo when on; picked-school chips with 44px remove.
- **S-30:** Saved (forest ★ context) and Following (teal chip) sections, ► follow copy: *"Following marks a school for future verified updates. Prototype: no notifications are sent."*
- **Reviewer rig (build-only):** ► opens from an **in-flow header button**; adds **Baseline mode** (also `&baseline=1` in the hash query) hiding all reviewer UI; frame-width presets are labelled **design-preview-only**.
- Unchanged from C: banners with mono kickers + wire codes, refusal `<dialog>` (`COMPARE_LIMIT_EXCEEDED · max_allowed: 4`, zero mutation), skeletons (`aria-busy`), 44–56px targets, skip link, `aria-live` announcements, `:focus-visible` (now indigo).

## Layout
Mobile-first column (max 660px) → two-up cards/questions ≥760px → ► **three-column S-27 cards ≥1360px** (frozen decision). Bottom tab bar with safe-area padding. No fixed overlay except the tab bar (guarded); tray is sticky in-flow.
