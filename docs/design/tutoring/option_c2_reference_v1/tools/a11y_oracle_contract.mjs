/* Option C2 accessibility ORACLE — measurement contract and WCAG 1.4.11
   adjudication register.

   This file is the single place where a non-text row may be declared
   NOT_APPLICABLE. Every declaration must name the visible feature that
   identifies the control; the reporter then measures THAT feature against its
   actual adjacent background and refuses the waiver if the feature itself
   fails 3:1 (see tools/a11y_oracle_core.mjs and the self-tests).
   A control facet with no entry here is reported ADJUDICATION_INVALID, which
   blocks, so no control can be quietly dropped from the evidence. */
export { validateProvenance } from './a11y_oracle_core.mjs';

export const VIEWPORT = { width: 390, height: 844 };

/* mandatory S-35 live-room state set */
export const ALL_STATES = [
  's35-room-live', 's35-room-waiting', 's35-prejoin', 's35-room-camoff', 's35-room-muted',
  's35-reconnecting', 's35-icefail', 's35-leave-confirm', 's35-perm-cam', 's35-review-open'
];
export const ALL_THEMES = ['light', 'dark'];

export const CONTROLS = [
  { sel: '[data-testid=session-info]', name: 'Session, connection and privacy details',
    identify: { feature: 'icon glyph', selector: '[data-testid=session-info] svg.ic' } },
  { sel: '[data-testid=mic]', name: 'Mute microphone / Unmute microphone',
    identify: { feature: 'icon glyph', selector: '[data-testid=mic] svg.ic' } },
  { sel: '[data-testid=cam]', name: 'Turn camera off / Turn camera on',
    identify: { feature: 'icon glyph', selector: '[data-testid=cam] svg.ic' } },
  { sel: '[data-testid=devices]', name: 'Device settings',
    identify: { feature: 'icon glyph', selector: '[data-testid=devices] svg.ic' } },
  { sel: '[data-testid=leave]', name: 'Leave',
    identify: { feature: 'icon glyph plus a visible "Leave" text label', selector: '[data-testid=leave] svg.ic' } },
  { sel: '[data-testid=self-min]', name: 'Minimise self-view',
    identify: { feature: 'icon glyph', selector: '[data-testid=self-min] svg.ic' } },
  { sel: '[data-testid=self-move]', name: 'Move self-view to another corner',
    identify: { feature: 'icon glyph', selector: '[data-testid=self-move] svg.ic' } }
];

const NA = (reason) => ({ status: 'NOT_APPLICABLE', reason });
const AP = (reason) => ({ status: 'APPLICABLE', reason });

/* key = "<stable selector>|<facet>"   facet = surface | border */
export const ADJUDICATION = {
  '[data-testid=session-info]|surface': NA(
    'The round fill is decorative. The information REQUIRED to identify this control is the info glyph, which is painted in --studiotx directly on that fill and is measured below; the control also carries an accessible name. WCAG 1.4.11 scopes the 3:1 floor to the visual information required to identify the component, so the decorative fill is out of scope.'),
  '[data-testid=session-info]|border': NA(
    'The 1.5px hairline is a decorative edge; deleting it leaves the info glyph fully legible and the control still identifiable. The glyph is measured against its actual adjacent background (the button fill).'),
  '[data-testid=mic]|surface': NA(
    'The unpressed fill is decorative. Both the control AND its muted/unmuted state are carried by the glyph itself (microphone vs microphone-with-slash) at high contrast on that fill, and the state is additionally exposed through aria-pressed. The fill is not the state indicator.'),
  '[data-testid=mic]|border': NA(
    'Decorative 2px ring. The microphone glyph identifies the control and its state; the ring carries no information the glyph does not.'),
  '[data-testid=cam]|surface': NA(
    'The fill is decorative. Camera on/off is carried by the glyph (camera vs camera-with-slash) plus aria-pressed, not by the fill.'),
  '[data-testid=cam]|border': NA(
    'Decorative 2px ring; the camera glyph identifies the control and its state.'),
  '[data-testid=devices]|surface': NA(
    'The fill is decorative; the device glyph identifies the control.'),
  '[data-testid=devices]|border': NA(
    'Decorative 2px ring; the device glyph identifies the control.'),
  '[data-testid=self-min]|surface': NA(
    'The translucent black disc is a legibility backing placed over live video, not the identifying feature. The white minimise glyph painted on that disc identifies the control and is measured against the disc, which is its ACTUAL adjacent background.'),
  '[data-testid=self-min]|border': NA(
    'Decorative 1.5px edge inside the self-view tile; the white glyph on its own backing disc identifies the control.'),
  '[data-testid=self-move]|surface': NA(
    'The translucent black disc is a legibility backing over live video; the white move glyph identifies the control and is measured against the disc.'),
  '[data-testid=self-move]|border': NA(
    'Decorative 1.5px edge; the white glyph on its own backing disc identifies the control.'),
  '[data-testid=leave]|surface': NA(
    'The pill fill is the same neutral studio surface used by every other dock control and therefore carries no identifying information; the leave glyph and the visible "Leave" label identify the control.'),
  '[data-testid=leave]|border': AP(
    'APPLICABLE. The tinted boundary is the only visual feature that separates the DESTRUCTIVE dock control from the three neutral dock controls, and at <=360px the visible "Leave" text is clipped to a visually hidden span so the pill edge plus glyph are all that remain. It is therefore visual information required to identify the component under 1.4.11 (and the colour-carried distinction under 1.4.1), so it must reach 3:1 against the dock surface.')
};

/* Focus indicators are never adjudicated away: a visible keyboard focus
   indicator must independently reach 3:1 against every adjacent colour. */
export const FOCUS_POLICY = {
  productDecisionEscapeHatch: false,
  note: 'A keyboard focus indicator below 3:1 is an implementable accessibility defect, not a product preference.'
};

/* Documented, non-WCAG reference finding. Kept visible, never counted as A/AA. */
export const BEST_PRACTICE_ONLY_RULE_IDS = ['page-has-heading-one'];
export const BEST_PRACTICE_NOTE = {
  'page-has-heading-one': 'Best practice (axe "best-practice" tag), NOT WCAG A or AA. The reference harness renders one S-35 state at a time into a bare document, so the document-level h1 belongs to the production route shell rather than to the reference frame. Recorded as a reference finding; production routes must still expose a correct heading hierarchy.'
};
