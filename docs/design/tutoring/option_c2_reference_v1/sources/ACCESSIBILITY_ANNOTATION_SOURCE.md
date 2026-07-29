# Accessibility Annotation (WCAG 2.2 AA target)

- **Keyboard**: skip link first; native controls only; logical order header → journey nav → content → actions; visible `:focus-visible` (2.5px) everywhere; refusal/cancel dialogs are native `showModal()` (focus-trapped, Esc closes); sticky bars have a focusin guard so focus never hides beneath them.
- **Route focus**: forward hash navigation scrolls to top and focuses the destination `h1` (`tabindex="-1"`, no duplicate announcement); Back restores prior scroll.
- **Live regions**: single polite `#live` region announces hold milestones (“Two minutes left…”), payment outcomes, mute/camera (“Camera off — device released”), preview start/stop, reconnect, refund submission, review submission.
- **Timer**: hold band is `role=timer` with an accessible name; urgency adds shape + words (“ENDING — UNDER 2 MIN”), never colour alone.
- **Status**: every chip = glyph + text; muted/cam-off/active-speaker states carry text (sr-only where visual is iconic).
- **Targets**: all actionable controls ≥44×44 (buttons 46–48, room controls 46–48, stars 46, slots 48).
- **Forms**: labelled fields; `aria-invalid` + inline error text on validation; OTP attempts left stated in words.
- **Captions/transcript**: not shown as functioning (future-ready slot documented in VIDEO_STATE_MAP; excluded from UI per brief).
- **Contrast**: 54 token pairs computed in TOKEN_COMPONENT_INVENTORY — 0 failures; instrumented axe sweep still recommended on the chosen option.
- **Currency/time**: Indian grouping from integer paise (₹1,060.82-style), Asia/Kolkata (IST) named on every session surface.
- **No PAN/CVV/OTP** in URLs, storage, logs or screenshots — card fields are visual hosted-field stand-ins containing only the published fictional test numbers.