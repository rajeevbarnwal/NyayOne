# Accessibility and interaction specification

Labels: `PRODUCT_APPROVED` where the obligation comes from an approved source, `PROPOSED` where
this package specifies it, `BROWSER_MEASURED` where it is asserted by the harness.

## 1. Target size — WCAG 2.2 AA 2.5.8

`PRODUCT_APPROVED` (independent review item 6; SAATHI-125 TC-65-11). Floor is 44 x 44 CSS px for
every actionable control, including the room's session-info control and the self-view Move and
Minimise controls that previously measured 40 and 30 px.

`BROWSER_MEASURED` — 0 violations across 1,968 rows. Token: `--target-min: 44px`;
primary controls use `--target-primary: 48px`.

A visually hidden input (the star rating radios) is not itself the target; its labelling `<label>`
is, and that label is 44 x 44. This is asserted, not assumed (NEG-REV-11).

## 2. Focus

`PROPOSED`, `BROWSER_MEASURED`.

- `:focus-visible` renders a 3 px `--terra` outline with 2 px offset in both themes.
- **Details sheet:** opening moves focus to the sheet's close control; closing returns focus to
  the invoking session-info control. Asserted on all 264 room rows
  (`focusMovedIntoSheet`, `focusRestoredOnClose`).
- **Modal dialogs** (`s33-back-warning`, `s35-confirm-modal`, `s35-leave-confirm`): focus moves to
  the first control inside the dialog, Tab is trapped inside the dialog, and the entire background
  (`.tbar`, `.body`, `.dock`, `.lh`, `.stage`, `.lctrl`, `.sheet`) is set `inert` and
  `aria-hidden`. Asserted as `modalFocusInside` and `modalBackgroundInert`.
- Escape closes the details sheet and returns focus to the invoker.
- DOM order equals visual order in every family; there is no positive `tabindex` anywhere.

## 3. Announcements

`PROPOSED`. A single `aria-live="polite" aria-atomic="true"` region is cleared and refilled on the
next animation frame so repeated identical messages are re-announced.

| Event | Announcement |
|---|---|
| Microphone toggled | "Microphone on" / "Microphone muted" |
| Camera toggled | "Camera on" / "Camera off — device released" |
| Sheet opened / closed | "Session details opened" / "Session details closed" |
| Self-view moved / minimised | "Self-view moved to bottom left" etc. |
| Hold under two minutes | urgent hold state announces on entry |
| Refund / attendance / review outcome | announced on entry to the state |

Refusals use `role="alert"` (assertive) on error banners; progress and status use `role="status"`.

## 4. Never colour alone

`PRODUCT_APPROVED` (independent review; the approved 82-state inventory row 8).

- **Hold urgency** under two minutes: border width increases from 1.5 px to 3 px, the remaining
  time is underlined, and the copy changes to "Under two minutes left." Asserted by NEG-HOLD-06,
  which reads the computed border width and the wording, not the hue.
- **Slot status**: available / held by another student / booked are words inside each chip, and
  non-bookable slots are `disabled` + `aria-disabled`. Asserted by NEG-SLOT-01/02.
- **Chips** carry a shape token as well as a colour: circle (jade), rotated square (terracotta),
  square (indigo), triangle (gold).
- **Refund progress** is "Step N of 5" as text plus a segmented bar.

## 5. Names, roles and relationships

- Every icon-only control has an `aria-label` that carries its *state*, not just its function
  ("Mute microphone" / "Unmute microphone"), and `aria-pressed` reflects the toggle.
- Every decorative SVG is `aria-hidden="true" focusable="false"`. Every meaningful SVG has
  `role="img"` and an `aria-label`.
- Invalid fields set `data-invalid="1"` and `aria-describedby` pointing at a real element id.
  Asserted by NEG-CARD-05.
- The star rating is a `role="radiogroup"` of five labelled radios inside a `fieldset`/`legend`.
- Character counters are `aria-live="polite"` and are hard-capped by `maxlength`.
- The hold timer is `role="timer"` with the remaining time in its accessible name.
- Disabled primary actions are `aria-disabled` **and** carry a visible text reason
  (`s34-join-early` uses `aria-describedby` to point at that reason).

## 6. Motion

`PROPOSED`. Only one transition exists in the whole reference: the details sheet's
`transform` at `--motion-base: .22s ease`. Under `prefers-reduced-motion: reduce` the motion
tokens collapse to `0s` and the transition is not applied. Asserted by NEG-RSP-04 (computed
`transition-duration` contains no non-zero digit) and by the 328-row reduced-motion pass.

## 7. Touch and pointer

`PRODUCT_APPROVED` refinement (independent review): hover-only help is insufficient on phones.
This reference therefore carries **no hover-only tooltip**. Unfamiliar actions use visible text
labels; icon-only controls are limited to conventional, low-ambiguity actions (mic, camera,
devices, copy, share, download, move, minimise, close). Financial, destructive and lifecycle
actions — Pay, Cancel & refund, Leave, Join, Confirm, Submit — are always icon **plus** text.

## 8. Reduced-capability paths

Every permission and device refusal offers a concrete recovery and, where the session can still
proceed, a reduced-capability alternative (camera denied or missing offers "Join with audio only").
Asserted by NEG-PERM-01…04.

## 9. Privacy obligations in the UI

`PRODUCT_APPROVED` (D-05). No PAN, security code, authentication code, join credential, device
name or media stream is written to the address bar, web storage, a cookie or any log. The
reference writes **no** storage and **no** cookie at all; five canary strings assert this against
`location.href`, `document.cookie`, both web storages and the full serialised DOM
(NEG-PRIV-01…04, all PASS).

## 10. Known gaps

- Colour-contrast ratios were not computed programmatically in this pass. The colour ramps are
  carried over unchanged from the approved C2 package, whose own `ACCESSIBILITY_PRECHECK.md`
  covers them. Recording this honestly rather than claiming an unmeasured pass.
- Screen-reader behaviour was not verified with a real assistive technology. Only the DOM
  contract (roles, names, relationships, live regions, focus order, inertness) is asserted.
