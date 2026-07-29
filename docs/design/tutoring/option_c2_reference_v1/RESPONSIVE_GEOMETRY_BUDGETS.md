# Responsive geometry budgets

All numbers below are `BROWSER_MEASURED` in headless Chromium at deviceScaleFactor 1 against
`reference/index.html`, fixture checksum `d45aa35d5614afe2`. Raw rows:
`MEASURED_GEOMETRY_RESULTS.json` (1,968 rows).

## 1. Binding budgets

| Budget | Value | Scope | Result |
|---|---|---|---|
| Horizontal overflow | 0 px | every state, every viewport, every theme | 0 violations in 1,968 rows |
| Minimum actionable target | 44 x 44 CSS px | every actionable control | 0 violations in 1,968 rows |
| Live-room page scroll | exactly 0 px | `room` family only | 0 violations in 264 room rows |
| Live-room root height | exactly `100dvh` (== clientHeight) | `room` family only | 264/264 exact |
| Control dock visible | always | `room` family only | 264/264 |
| Details sheet adds page height | 0 px | `room` family only | 264/264 |
| Focus restored on sheet close | required | `room` family only | 264/264 |
| Sticky dock covers final content | never | `checkout`, `manage`, `prejoin` | 0 violations |
| Console errors | 0 | every row | 0 |
| Network requests | 0 | every row | 0 (fully offline) |

Vertical scrolling is **permitted** on the `list`, `profile`, `checkout`, `receipt`, `manage` and
`prejoin` families. It is **forbidden** on the `room` family. That distinction is the whole point
of the correction mandate and is enforced per family, not globally.

## 2. Measured matrix

| Pass | Viewports | Themes | Rows | PASS | FAIL |
|---|---|---|---:|---:|---:|
| main | 390x844, 430x932, 844x390, 932x430, 768x1024, 1024x768, 1440x900 | light + dark | 1,148 | 1,148 | 0 |
| reduced-motion (`prefers-reduced-motion: reduce`) | 390x844, 430x932, 844x390, 932x430 | light | 328 | 328 | 0 |
| 200% zoom (halved CSS viewport) | 195x422, 720x450 | light | 164 | 164 | 0 |
| safe-area (portrait 47/34 px, landscape 44 px left+right, 21 px bottom) | 390x844, 430x932, 844x390, 932x430 | light | 328 | 328 | 0 |
| **Total** | | | **1,968** | **1,968** | **0** |

Every one of the 82 states is measured in every pass.

## 3. Live-room boundary — before and after

`BROWSER_MEASURED`. Before rows are reproduced against the historical package, read-only.

| Frame | Viewport | Before scroll | After scroll | Before min target | After min target | Verdict |
|---|---|---:|---:|---:|---:|---|
| S-35 live portrait | 390x844 | 308 px | **0 px** | 40 px | **44 px** | PASS |
| S-35 live portrait | 430x932 | 308 px | **0 px** | 40 px | **44 px** | PASS |
| S-35 live landscape | 844x390 | 281 px | **0 px** | 40 px | **44 px** | PASS |
| S-35 live landscape | 932x430 | 290 px | **0 px** | 40 px | **44 px** | PASS |

Room root height equals client height exactly at every measured viewport: 844, 932, 390, 430,
1024, 768 and 900 px.

## 4. Reflow rules

| Breakpoint | Behaviour | Rationale |
|---|---|---|
| `<= 360px` (includes 200% zoom on a 390 px phone) | Two-column grids collapse; key/value rows, chip rows, action rows and the room control dock **wrap**; the room clock and the screen-id badge move out of the header (the clock stays available in the session-details sheet) | WCAG 2.2 1.4.10 Reflow. **No interactive control is ever removed** — mic, camera, devices and Leave stay in the dock and the room stays exactly 100dvh, with the media stage absorbing the extra dock row. |
| `<= 280px` | The room "Live" chip is hidden; the live state remains in the tile and in the accessible name | Extreme zoom only. |
| `orientation: landscape and max-height: 520px` | Header height 56 -> 44 px, stage padding 8 -> 6 px, self-view 96x128 -> 72x54 px, dock padding reduced, sheet max-height 70dvh -> 88dvh | The correction mandate requires landscape compaction without removing controls. |

## 5. Long-content and font resilience

- Every heading, paragraph, chip, banner and key/value value uses `overflow-wrap:anywhere`, so an
  unbroken 90-character name or a pasted reference cannot force horizontal overflow (NEG-PROF-01,
  NEG-RSP-01).
- At a root font size of 32 px (roughly 200% user font size) there is no horizontal overflow and
  no control drops below 44 px (NEG-RSP-03).
- The sticky dock reservation is **measured at runtime**, not guessed: `app.js` sets the body's
  bottom padding to the dock's real height plus 16 px before the ready signal resolves. That is
  why `stickyCoversFinalContent` is false on every row at every viewport.

## 6. Safe area

`--safe-t/b/l/r` map to `env(safe-area-inset-*)` with a `0px` fallback. The room header adds the
top inset, the room dock and every sticky dock add the bottom inset, and the room root adds the
left/right insets. Under the simulated notch the Leave control's bottom edge stays inside the
viewport at all four mobile viewports (328/328 rows).

## 7. Measurement method

- One page per (pass, viewport, theme); states are advanced in-page, so no reload noise.
- Every navigation awaits `window.__C2_READY` with a bounded rejecting 15 s timeout.
  **There is no fixed sleep anywhere in the harness.**
- The details-sheet transition is temporarily set to `none` before the sheet geometry is read, so
  the settled position is measured rather than a frame mid-animation.
- Controls inside a horizontal scroller (the S-31 practice-area rail) are checked against that
  scroller's scroll width, not the viewport — the rail is intentionally swipeable and carries a
  fade affordance.
- Visually hidden inputs (the star radios) are excluded only when their labelling ancestor is
  >= 44x44; the ancestor is the measured target.
- While a modal is open the background is `inert`, and inert subtrees are excluded from
  reachability and overlap checks.
