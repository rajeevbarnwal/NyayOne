# Token, component and motion specification

## 1. Colour tokens — `PRODUCT_APPROVED`

Copied verbatim from the approved C2 package
(`tutoring_option_c2_mobile_gate_2026-07-29/C2_MOBILE_GATE.html`). No value was changed, added or
removed. Full definitions: `reference/tokens.css`.

| Group | Light | Dark | Use |
|---|---|---|---|
| Surface | `--bg #fbf7f0`, `--card #fff`, `--soft #f4ece0` | `--bg #140e06`, `--card #1f170d`, `--soft #291f12` | page, cards, wells |
| Ink | `--ink #211609`, `--ink2 #4d4234`, `--mut #6f6248` | `--ink #f7f0e2`, `--ink2 #dbcdb7`, `--mut #ad9d81` | primary, secondary, muted text |
| Line | `--line #ead9c2`, `--line2 #d3bd9e` | `--line #3a2d1b`, `--line2 #50402a` | hairlines, control borders |
| Jade | `--jade #0f6b47`, `--jadeq #e3f1e9` | `--jade #5fcb9c`, `--jadeq #162d20` | confirmation, verified, money returning |
| Terracotta | `--terra #a8410c`, `--terraq #fdeadd` | `--terra #f2986a`, `--terraq #37200f` | time pressure, eyebrows, focus ring |
| Indigo | `--indigo #3f4796`, `--indigoq #eceefb` | `--indigo #a4abf5`, `--indigoq #23264a` | informational, education |
| Gold | `--gold #8a6108`, `--goldq #faf0d6` | `--gold #e6bf6a`, `--goldq #332612` | rating, review |
| Risk | `--risk #98281d`, `--riskq #fae9e5` | `--risk #ef9c8b`, `--riskq #361d17` | destructive, refusal |
| Studio | `--studio #120d07`, `--studio2 #1e160d`, `--studiotx #f6efe2`, `--studiomut #ad9c80` | `--studio #0c0803`, `--studio2 #191207` | the live room only |

`PROPOSED` additions (naming only, no new values): `--studio-line`, `--studio-line2`,
`--studio-leave`, `--studio-leave-ink` give names to literals that were previously inline in the
approved room CSS.

`PROPOSED` accessibility additions (SAATHI-129). Both are theme-invariant, exactly like the
`--studio-*` tokens above, because the studio surfaces are dark in both themes:

| Token | Value | Purpose | Measured |
|---|---|---|---|
| `--studio-leave-edge` | `#a4503f` | destructive dock-control boundary, the only visual feature separating it from the neutral dock controls (WCAG 1.4.11) | 3.60:1 light / 3.67:1 dark against the dock surface (was `--studio-leave` at 2.74:1 / 2.79:1) |
| `--studio-focus` | `#f2986a` | keyboard focus ring on the dark studio surfaces (WCAG 1.4.11 + 2.4.7); the value is the already-approved dark-theme `--terra` | 8.06:1 – 9.17:1 against every studio surface (was `--terra` at 2.91:1 on the self-view tile in the light theme) |

Hue, geometry and every other approved value are unchanged; the sheet and the leave dialog keep the
global `--terra` focus ring because they are painted on the light card surface.

## 2. Type — `PRODUCT_APPROVED`

| Token | Family | Use |
|---|---|---|
| `--font-display` | Newsreader (serif) | headings, tutor names, refund amount, medallion monogram |
| `--font-body` | Hanken Grotesk | all body copy and controls |
| `--font-mono` | IBM Plex Mono | money, references, timers, eyebrows, metadata |

The Latin subsets of all three families are extracted **verbatim** from the approved C2 bundle and
embedded as `.woff2` files under `reference/assets/fonts` (196 KB total, four files, nine faces).
`font-display: block` keeps text metrics stable, and the ready signal waits on
`document.fonts.ready`, so no capture is taken mid-swap. The reference makes **no** network
request.

## 3. Spacing, radius, target and motion — `PROPOSED` (names for approved values)

`--t-1..--t-8` = 4/6/8/10/12/14/18/22 px · `--r-sm/md/lg/xl/pill/round` = 11/14/18/20/24/50% ·
`--target-min` 44 px, `--target-primary` 48 px · `--motion-fast` .12s, `--motion-base` .22s,
`--motion-ease` ease · `--safe-t/b/l/r` = `env(safe-area-inset-*, 0px)`.

Under `prefers-reduced-motion: reduce` the motion tokens are redefined to `0s`.

## 4. Component inventory

| Component | Class | Notes |
|---|---|---|
| Top bar | `.tbar` | sticky, safe-area top, carries the screen id badge |
| Button | `.btn` (`.jade`, `.terra`, `.block`) | 48 px min height; financial/destructive/lifecycle always icon+text |
| Icon button | `.ib` | 44 x 44 minimum, conventional actions only |
| Chip | `.chip` (`.g .t .i .gd .r`) | colour **and** shape token |
| Banner | `.banner` (`.ok .warn .err .info`) | typed state surface; `role=alert` when `.err` |
| Disclosure | `.dis > summary + .dbody` | 48 px summary, no custom marker |
| Key/value | `.kv` | wraps below 360 px |
| Sticky dock | `.dock`, `.dockrow` | safe-area bottom; body padding is set to the dock's **measured** height |
| Hold | `.hold[data-urgent]` | non-colour urgency |
| Field | `.fld`, `.in`, `.in.hosted`, `.err` | hosted card treatment; `data-invalid` + `aria-describedby` |
| Tutor card | `.tut` | S-31 |
| Profile header + slots | `.phead`, `.slots`, `.slotbtn`, `.edu`, `.svr` | **S-32, new** — Option C structure, C2 tokens |
| Confirmation | `.band`, `.seal` | S-34 |
| Refund | `.amt`, `.prog`, `.steps` | S-35 |
| Device preview | `.preview`, `.sel` | S-35 pre-join |
| Live room | `.route.room`, `.lh`, `.stage`, `.mtile`, `.self`, `.selfctl`, `.sb`, `.lctrl`, `.cb`, `.sheet`, `.scrim`, `.rbanner`, `.stateveil` | **repaired**; see below |
| Modal | `.modal` + `.scrim` | `max-height: calc(100dvh - 24px)`, background `inert` |

## 5. The repaired live room — `PROPOSED`, `BROWSER_MEASURED`

```css
html[data-family=room], body[data-family=room]{height:100%;overflow:hidden;overscroll-behavior:none}
.route.room{height:100dvh;max-height:100dvh;
  display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr) auto;
  overflow:hidden;position:relative}
.room>.lh,.room>.stage,.room>.lctrl{min-width:0}
.room .stage{display:grid;grid-template-rows:minmax(0,1fr);overflow:hidden;contain:strict}
.room .self{position:absolute;max-width:44%;max-height:44%;contain:layout size}
.room .lctrl{padding-bottom:calc(8px + var(--safe-b))}
.room .sheet{position:fixed;bottom:0;max-height:70dvh}
```

Three rules carry the whole correction:

1. `grid-template-columns:minmax(0,1fr)` plus `min-width:0` on each row. Without them the implicit
   `auto` column sizes to max-content and the header and dock overflow to 435 px at a 390 px
   viewport — silently, because `overflow:hidden` hides it. This was found by measurement, not by
   inspection.
2. `position:fixed` on the sheet. This is the direct fix for the 308 px defect: a fixed element
   cannot contribute to document scroll height.
3. `minmax(0,1fr)` on the stage row plus `contain:strict`. The media stage absorbs every size
   change, so the self-view, a wrapped dock or a taller header can never grow the room.

## 6. Motion inventory

| Element | Property | Duration | Reduced motion |
|---|---|---|---|
| Details sheet | `transform` (+ `visibility` step) | `--motion-base` .22s ease | not applied |
| Everything else | — | none | — |

There is no entrance animation, no skeleton shimmer, no parallax and no auto-playing motion
anywhere in the reference. The single transition is the only thing `prefers-reduced-motion` has to
disable, which is why the reduced-motion assertion is a single computed-style read.
