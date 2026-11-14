# S-35 product-capture contract

This producer adds 56 design states at mobile390 and desktop (112 light rows),
after the existing 340 measured rows. It does not change product code, frozen
reference bytes, tolerances, historical producers or exception records.

## Evidence limits

- All rows execute the actual `/s-35` application. API responses are synthetic,
  backend-shaped fixtures with strict ordered method/path/query/body checks.
  No React state, query cache, markup, styles or navigation is injected.
- Reviews are created through the actual POST action before edit/delete flows;
  no review-read endpoint is invented. Errors use actual HTTP error statuses.
- Browser-device rows emulate secure-context/media-device API outcomes. Room
  rows use the application's existing explicit deterministic transport opt-in.
  Neither is real hardware/permission-prompt, media-provider or backend QA.
- `room-connecting` uses the real retry action after a simulated transport
  failure, with the next join-credential response held pending. It records the
  application's connecting UI while awaiting admission, **not** an established
  provider connection. The prior credential is not reused as proof of entry.
- `left` records the actual attendance destination after leaving the room. It is
  labelled `live-route-destination`, not a frozen “left” page or video teardown QA.
- The owner approved `refund-pending` / `refund-failed` (four viewport rows) as
  `live-capability-gap` evidence. Cancellation returns an assessment; no student
  refund-status read exists. Both capture “settlement not confirmed”, and
  `settlementStateObserved` must remain false. Neither settlement state is claimed.
- A test clock begins at 2026-09-28T10:00:00Z. Zero-duration task pumping allows
  genuine asynchronous UI updates; explicit interaction steps advance it by
  fixed durations. Images use the paused clock. Axe runs with the clock resumed
  **after** raw image/geometry capture. No screenshot selection by approval hash,
  retry-to-match, pixel rewriting or masks are introduced.
- Document-top framing preserves the active element. Each product row uses a
  separate same-version Chromium process with partial raster disabled; historical
  captures continue using their original browsers and producer code.

## Fail-closed boundaries

The imported cache is verified before capture; each PNG's bytes and dimensions
are rechecked. Missing/tampered references, missing/duplicate/invented row IDs,
unexpected API calls, console/network errors and incomplete route/terminal-state
proof fail closed. Capability-gap/destination labels cannot be replaced by plain
live-page claims. Existing serious/critical accessibility and pixel/geometry
rules remain active. No new exception approval is included in this bundle.

`nyay66-s35-fixtures.browser-contract.mjs` exercises all 112 routes, then two cold
producer passes and missing/tampered reference rejection. Local diagnostics are
not hosted conformance or independent Claude QA. Hosted measurement follows
owner integrity approval; measured differences require review before exceptions.
