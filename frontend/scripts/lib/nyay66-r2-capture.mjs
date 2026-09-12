// Capture configuration for reviewer chrome, never application styling.
export function removeR2ReviewerClipping() {
  const viewport = document.querySelector('.vp');
  if (!viewport) throw Error('R2_CAPTURE_VIEWPORT_MISSING');
  // .vp belongs to the reviewer device frame. Keep its dimensions/scrolling
  // and every descendant application's style intact; capture the full rectangle.
  viewport.style.borderRadius = '0px';
}
