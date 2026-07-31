# Option C2 Mobile Gate — Independent Product/UX Review

**Date:** 29 July 2026  
**Design package:** `/Users/rajeevbarnwal/Desktop/Codes/LegalSaathi/docs/design/tutoring_option_c2_mobile_gate_2026-07-29`  
**Reviewer:** Independent Product/UX review  
**Decision:** **CONDITIONAL APPROVAL — approve the C2 visual direction and four compressed flows; do not approve the live-room mobile gate yet.**

## Executive assessment

Option C2 now has a coherent, human LegalSaathi identity. It feels calmer and more trustworthy than the earlier robotic/icon-heavy direction. The design makes strong use of editorial typography, warm neutrals, restrained colour and clear financial/status hierarchy.

The following representative flows are ready to be used as the design source for full-state expansion, subject to normal implementation QA:

- S-31 marketplace
- S-33 payment and booking hold
- S-34 confirmation
- S-35 cancellation/refund

The S-35 live-session portrait and landscape compositions fail their own mandatory mobile requirements and must receive one focused correction before the package is considered final.

## Live DOM geometry results

The package's own `Run geometry checks` control was executed in the in-app Chromium browser in both light and dark modes. Results were identical across themes.

| Screen | Viewport | Scroll beyond viewport | Horizontal overflow | Minimum target | Product result |
|---|---:|---:|---:|---:|---|
| S-31 marketplace | 390×844 | 138 px | 0 | 44 px | PASS |
| S-31 marketplace | 430×932 | 50 px | 0 | 44 px | PASS |
| S-33 payment + hold | 390×844 | 73 px | 0 | 44 px | PASS |
| S-33 payment + hold | 430×932 | 0 | 0 | 44 px | PASS |
| S-34 confirmed | 390×844 | 0 | 0 | 44 px | PASS |
| S-34 confirmed | 430×932 | 0 | 0 | 44 px | PASS |
| S-35 refund | 390×844 | 0 | 0 | 44 px | PASS |
| S-35 refund | 430×932 | 0 | 0 | 44 px | PASS |
| S-35 live portrait | 390×844 | **309 px** | 0 | **40 px** | **FAIL** |
| S-35 live portrait | 430×932 | **309 px** | 0 | **40 px** | **FAIL** |
| S-35 live landscape | 844×390 | **621 px** | 0 | **40 px** | **FAIL** |
| S-35 live landscape | 932×430 | **581 px** | 0 | **40 px** | **FAIL** |

The committed `MOBILE_GEOMETRY_RESULTS.json` is still a pending schema with no measured screen rows. The final package must replace it with the actual measured output from the corrected build.

## What works well

### S-31 marketplace

- Strong editorial opening without oversized decorative content.
- Search and practice-area selection are immediately understandable.
- The first mentor card is complete in the first viewport and has an explicit `View & book` action.
- Progressive disclosure protects mobile density without hiding the primary decision inputs.

### S-33 payment + hold

- The tutor, appointment and hold countdown establish context before card entry.
- “Test environment · fictional card” is visible and appropriately separated from production trust messaging.
- Payment protection and fee breakdown are disclosed progressively.
- The sticky amount/payment action avoids forcing users to find the primary action after scrolling.

### S-34 confirmation

- This is the strongest screen in the package.
- Confirmation, tutor, date/time, join and management actions fit without scrolling.
- Copy/share/download are secondary and visually subordinate.
- Refund eligibility remains visible without competing with the join action.

### S-35 refund

- Calm, reassuring hierarchy appropriate for a cancellation moment.
- Amount, destination and timing are visible before disclosure.
- The reschedule alternative is present without dark-pattern pressure.
- Progress and refund explanations remain available without lengthening the default view.

## Blocking correction: S-35 live session

The live room currently looks cinematic, but its operational controls are not reliably available in the viewport. In landscape, the measured scroll exceeds the viewport by 581–621 px and the screenshot shows no media controls. A video room cannot require page scrolling to mute, stop camera or leave.

Apply these changes only to the live-room states:

1. Make the live-room root exactly `100dvh` in portrait and landscape and set body/page scrolling to `overflow: hidden`.
2. Use a three-row composition:
   - compact session header;
   - flexible media stage using `minmax(0, 1fr)`;
   - fixed safe-area-aware control dock.
3. Keep microphone, camera, device settings and Leave visible at all times.
4. Move session details into an overlay/bottom sheet that does not affect page height.
5. Keep self-view within the media stage. Its Move and Minimise controls must not expand the stage.
6. Increase every interactive target—including session-info, Move and Minimise—to at least 44×44 CSS px.
7. In landscape, shorten the header and reduce self-view size; never remove the control dock.
8. Assert:
   - `scrollHeight <= clientHeight`;
   - zero horizontal overflow;
   - all primary controls intersect the viewport;
   - minimum target >= 44 px;
   - safe-area insets do not cover Leave or media controls.

## Non-blocking refinements

- The S-31 practice-area rail intentionally clips at the right edge. Add a subtle fade or “swipe for more” affordance on first use so the clipping reads as horizontal navigation, not a layout defect.
- Freeze a touch behavior for icon help: visible label for unfamiliar actions, or tap-to-open persistent tooltip/popover. Hover-only help is insufficient on phones.
- At 200% zoom, recheck that the payment hold and sticky dock do not consume most of the usable viewport.
- Keep icon-only controls limited to conventional, low-ambiguity actions. Financial, destructive and lifecycle actions should remain icon-plus-text.

## Final recommendation

Approve **Option C2 as the Wave 2 visual direction** and freeze S-31, S-33, S-34 and S-35 refund as the reference compositions.

Do **not** freeze the S-35 live-room frames or expand them across all states until the four live-room geometry rows pass. This should be one bounded correction cycle; the other approved screens should not be redesigned again.
