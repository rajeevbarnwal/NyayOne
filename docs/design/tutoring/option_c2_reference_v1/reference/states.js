/* Option C2 reference — canonical 82-state model (v1).
   Generated from the approved 82-state inventory in
   docs/design/Payments_Refunds_Design/tutoring_payment_refund_options_2026-07-29/STATE_INVENTORY.md
   This file is the single source for STATE_INVENTORY.json and for the reference renderer. */
(function(root){'use strict';
var STATES=[
 {
  "index": 1,
  "id": "s31-default",
  "label": "Tutor discovery — results",
  "screen": "S-31",
  "trigger": "Student opens /s-31 with no filter",
  "requiredInfoActions": "Search input, practice-area rail, >=1 complete tutor card with fee and View & book",
  "category": "discovery",
  "serverAuthoritativeRule": "Result set, ranking and fee are server-owned; client never computes price",
  "typedError": "NONE:no error surface in this state",
  "recovery": "n/a — nominal state",
  "fixtureId": "fx.s31-default",
  "layoutFamily": "list",
  "a11yObligations": "Visible focus ring on every control; logical DOM order; 44px targets; search input has a visible-or-sr label; rail is a labelled group",
  "persistence": "URL only (?state); no PII in URL or storage",
  "provenance": "PRODUCT_APPROVED",
  "delta": {}
 },
 {
  "index": 2,
  "id": "s31-filtered",
  "label": "Discovery — filtered",
  "screen": "S-31",
  "trigger": "Student selects a practice-area rail chip",
  "requiredInfoActions": "Active filter indicated with aria-pressed, result count, clear-filter affordance",
  "category": "discovery",
  "serverAuthoritativeRule": "Filter is applied server-side; client shows only what the server returned",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Clear filter returns to s31-default",
  "fixtureId": "fx.s31-filtered",
  "layoutFamily": "list",
  "a11yObligations": "Visible focus ring on every control; logical DOM order; 44px targets; aria-pressed reflects filter state; result count announced",
  "persistence": "Filter in URL query only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "filtered"
  }
 },
 {
  "index": 3,
  "id": "s31-empty",
  "label": "Discovery — empty result",
  "screen": "S-31",
  "trigger": "Search or filter yields zero tutors",
  "requiredInfoActions": "Explicit empty explanation, the query echoed safely, at least one recovery action",
  "category": "discovery",
  "serverAuthoritativeRule": "Empty is a server result, never a client render failure",
  "typedError": "EMPTY_RESULT (PROPOSED label)",
  "recovery": "Clear filters / broaden search",
  "fixtureId": "fx.s31-empty",
  "layoutFamily": "list",
  "a11yObligations": "Visible focus ring on every control; logical DOM order; 44px targets; empty message in a live region; no dead-end",
  "persistence": "No state persisted",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "empty"
  }
 },
 {
  "index": 4,
  "id": "s32-profile",
  "label": "Tutor profile",
  "screen": "S-32",
  "trigger": "Student opens a tutor from S-31",
  "requiredInfoActions": "Identity, verification, practice area, experience, languages, rating, fee, duration, bio, availability entry",
  "category": "profile",
  "serverAuthoritativeRule": "Profile content and verification badge are server-owned",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Back to S-31",
  "fixtureId": "fx.s32-profile",
  "layoutFamily": "profile",
  "a11yObligations": "Visible focus ring on every control; logical DOM order; 44px targets; h1 is the tutor name; portrait is decorative (aria-hidden)",
  "persistence": "No state persisted",
  "provenance": "PROPOSED: composition newly added in this package — structure derived from the approved Option C S-32 frame, restyled with approved C2 tokens. Requires Product sign-off as a controlled adaptation.",
  "delta": {}
 },
 {
  "index": 5,
  "id": "s32-availability",
  "label": "Profile — availability (available/held/booked)",
  "screen": "S-32",
  "trigger": "Student scrolls to or opens the availability block",
  "requiredInfoActions": "Timezone label, slot list with available/held/booked distinguished by text not colour alone, disabled non-bookable slots",
  "category": "profile",
  "serverAuthoritativeRule": "Slot status and the 10-minute hold TTL are server-owned; immutable timezone-aware slot IDs",
  "typedError": "SLOT_UNAVAILABLE (PROPOSED label)",
  "recovery": "Choose another slot; refresh availability",
  "fixtureId": "fx.s32-availability",
  "layoutFamily": "profile",
  "a11yObligations": "Visible focus ring on every control; logical DOM order; 44px targets; each slot button announces status in its accessible name; disabled slots are aria-disabled",
  "persistence": "Selected slot id in URL only",
  "provenance": "PROPOSED: composition newly added in this package — structure derived from the approved Option C S-32 availability block, restyled with approved C2 tokens.",
  "delta": {
   "variant": "availability"
  }
 },
 {
  "index": 6,
  "id": "s33-summary",
  "label": "Order summary + slot",
  "screen": "S-33",
  "trigger": "Student confirms a slot and enters checkout",
  "requiredInfoActions": "Tutor, slot, timezone, fee breakdown, total, primary pay action, cancel",
  "category": "checkout-summary",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Cancel returns to S-32",
  "fixtureId": "fx.s33-summary",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {}
 },
 {
  "index": 7,
  "id": "s33-hold",
  "label": "Active 10-min hold (live countdown)",
  "screen": "S-33",
  "trigger": "A slot hold is created on entering checkout",
  "requiredInfoActions": "Remaining hold time as text, what expiry means, nothing-charged assurance",
  "category": "checkout-hold",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Hold expiry moves to s33-hold-expired",
  "fixtureId": "fx.s33-hold",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "hold"
  }
 },
 {
  "index": 8,
  "id": "s33-hold-urgent",
  "label": "Hold under 2 min — non-colour urgency",
  "screen": "S-33",
  "trigger": "Hold remaining drops below 120s",
  "requiredInfoActions": "Remaining time, a non-colour urgency cue (weight, underline, border, wording)",
  "category": "checkout-hold",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Complete payment or let it expire safely",
  "fixtureId": "fx.s33-hold-urgent",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "hold",
   "holdRemaining": "01:52",
   "urgent": 1
  }
 },
 {
  "index": 9,
  "id": "s33-card",
  "label": "Card entry (hosted-field treatment)",
  "screen": "S-33",
  "trigger": "Student continues to payment",
  "requiredInfoActions": "Provider-hosted card fields, test-environment label, protection disclosure",
  "category": "checkout-card",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Cancel payment; nothing charged",
  "fixtureId": "fx.s33-card",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "card"
  }
 },
 {
  "index": 10,
  "id": "s33-testhelper",
  "label": "Deterministic test-card helper",
  "screen": "S-33",
  "trigger": "Reviewer opens the test helper in a non-production build",
  "requiredInfoActions": "Explicit test-only banner, fictional card values, no production affordance",
  "category": "checkout-card",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Close helper",
  "fixtureId": "fx.s33-testhelper",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "card",
   "extra": "testhelper"
  }
 },
 {
  "index": 11,
  "id": "s33-validation",
  "label": "Card form validation errors",
  "screen": "S-33",
  "trigger": "Client-side field validation fails before submit",
  "requiredInfoActions": "Per-field error text tied by aria-describedby, error summary, focus to first error",
  "category": "checkout-card",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "FIELD_INVALID (PROPOSED label)",
  "recovery": "Correct the field and resubmit",
  "fixtureId": "fx.s33-validation",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "card",
   "extra": "validation"
  }
 },
 {
  "index": 12,
  "id": "s33-otp",
  "label": "Payment OTP / 3-DS challenge",
  "screen": "S-33",
  "trigger": "Provider requires an additional authentication step",
  "requiredInfoActions": "Challenge explanation, input, attempts remaining, expiry, resend, never-stored assurance",
  "category": "checkout-auth",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Resend or cancel",
  "fixtureId": "fx.s33-otp",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "otp"
  }
 },
 {
  "index": 13,
  "id": "s33-otp-resent",
  "label": "OTP resent (counter + expiry)",
  "screen": "S-33",
  "trigger": "Student requests a new challenge code",
  "requiredInfoActions": "Resend counter, new expiry, cooldown",
  "category": "checkout-auth",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Wait for cooldown or cancel",
  "fixtureId": "fx.s33-otp-resent",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "otp",
   "extra": "otp-resent"
  }
 },
 {
  "index": 14,
  "id": "s33-otp-wrong",
  "label": "OTP incorrect (attempts left)",
  "screen": "S-33",
  "trigger": "Provider rejects the entered code",
  "requiredInfoActions": "Typed error, attempts remaining, hold still valid, nothing charged",
  "category": "checkout-auth",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "AUTH_CHALLENGE_FAILED (PROPOSED label)",
  "recovery": "Re-enter or resend",
  "fixtureId": "fx.s33-otp-wrong",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "otp",
   "extra": "otp-wrong"
  }
 },
 {
  "index": 15,
  "id": "s33-otp-locked",
  "label": "OTP locked after 3 attempts",
  "screen": "S-33",
  "trigger": "Attempts exhausted",
  "requiredInfoActions": "Lock explanation, nothing charged, hold status, next step",
  "category": "checkout-auth",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "AUTH_CHALLENGE_LOCKED (PROPOSED label)",
  "recovery": "Start a new payment attempt or pick another slot",
  "fixtureId": "fx.s33-otp-locked",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "otp",
   "extra": "otp-locked"
  }
 },
 {
  "index": 16,
  "id": "s33-processing",
  "label": "Processing — awaiting provider",
  "screen": "S-33",
  "trigger": "Payment submitted, provider verification pending",
  "requiredInfoActions": "Non-spinner-only status text, do-not-close guidance, no success claim",
  "category": "checkout-outcome",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Wait; safe retry available if it stalls",
  "fixtureId": "fx.s33-processing",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "outcome",
   "extra": "processing"
  }
 },
 {
  "index": 17,
  "id": "s33-success",
  "label": "Success (server-verified event)",
  "screen": "S-33",
  "trigger": "Server receives the verified provider event",
  "requiredInfoActions": "Explicit server-verified wording, booking reference, continue to S-34",
  "category": "checkout-outcome",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Continue to confirmation",
  "fixtureId": "fx.s33-success",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "outcome",
   "extra": "success"
  }
 },
 {
  "index": 18,
  "id": "s33-declined",
  "label": "Card declined",
  "screen": "S-33",
  "trigger": "Provider declines the instrument",
  "requiredInfoActions": "Typed decline, nothing charged, hold status, alternative method",
  "category": "checkout-outcome",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "PAYMENT_DECLINED (PROPOSED label)",
  "recovery": "Try another card; hold still running",
  "fixtureId": "fx.s33-declined",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "outcome",
   "extra": "declined"
  }
 },
 {
  "index": 19,
  "id": "s33-provider-down",
  "label": "Provider unavailable",
  "screen": "S-33",
  "trigger": "Provider unreachable or erroring",
  "requiredInfoActions": "Typed provider failure, nothing charged, safe retry, hold protection",
  "category": "checkout-outcome",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "PROVIDER_UNAVAILABLE (PROPOSED label)",
  "recovery": "Safe retry with the same idempotency key",
  "fixtureId": "fx.s33-provider-down",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "outcome",
   "extra": "provider-down"
  }
 },
 {
  "index": 20,
  "id": "s33-cancelled",
  "label": "User cancelled payment",
  "screen": "S-33",
  "trigger": "Student cancels at the provider or in the form",
  "requiredInfoActions": "Nothing charged, hold still held until TTL, resume action",
  "category": "checkout-outcome",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "PAYMENT_CANCELLED (PROPOSED label)",
  "recovery": "Resume payment or release the slot",
  "fixtureId": "fx.s33-cancelled",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "outcome",
   "extra": "cancelled"
  }
 },
 {
  "index": 21,
  "id": "s33-hold-expired",
  "label": "Hold expired — slot released",
  "screen": "S-33",
  "trigger": "Hold TTL reaches zero",
  "requiredInfoActions": "Expiry explanation, nothing charged, slot released, pick-another action",
  "category": "checkout-hold",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "HOLD_EXPIRED",
  "recovery": "Pick another slot",
  "fixtureId": "fx.s33-hold-expired",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "outcome",
   "extra": "hold-expired"
  }
 },
 {
  "index": 22,
  "id": "s33-duplicate",
  "label": "Duplicate submit — idempotent replay",
  "screen": "S-33",
  "trigger": "Student submits twice with the same idempotency key",
  "requiredInfoActions": "Explicit charged-once wording, same result replayed, no second booking",
  "category": "checkout-outcome",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "DUPLICATE_SUBMIT",
  "recovery": "Open the existing booking",
  "fixtureId": "fx.s33-duplicate",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "outcome",
   "extra": "duplicate"
  }
 },
 {
  "index": 23,
  "id": "s33-retry",
  "label": "Safe retry (no double charge)",
  "screen": "S-33",
  "trigger": "Student retries after a provider failure",
  "requiredInfoActions": "Same idempotency key shown, no-double-charge assurance",
  "category": "checkout-outcome",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE",
  "recovery": "Retry or cancel",
  "fixtureId": "fx.s33-retry",
  "layoutFamily": "checkout",
  "a11yObligations": "Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "outcome",
   "extra": "retry"
  }
 },
 {
  "index": 24,
  "id": "s33-back-warning",
  "label": "Back-navigation warning during hold",
  "screen": "S-33",
  "trigger": "Student attempts to navigate back while a hold is active",
  "requiredInfoActions": "Warning dialog, consequence of leaving, stay/leave choice",
  "category": "checkout-hold",
  "serverAuthoritativeRule": "Payment state changes only on a server-verified provider event; the hold TTL and slot lock are server-owned; money is integer paise",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Stay on checkout or release the hold",
  "fixtureId": "fx.s33-back-warning",
  "layoutFamily": "checkout",
  "a11yObligations": "role=dialog + aria-modal, focus moved into dialog, ESC returns focus to invoker; Status changes announced via aria-live=polite; timer exposed as role=timer with a text value; errors tied to fields via aria-describedby; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable and URL-addressable; survives reload; no PAN/CVV/payment OTP stored anywhere",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "card",
   "overlay": "dialog",
   "extra": "back-warning"
  }
 },
 {
  "index": 25,
  "id": "s34-confirmed",
  "label": "Booking confirmed + receipt",
  "screen": "S-34",
  "trigger": "Server-verified payment completes",
  "requiredInfoActions": "Confirmed status, tutor, date/time, timezone, join eligibility, Join and Manage, booking reference",
  "category": "confirmation",
  "serverAuthoritativeRule": "Confirmation is rendered only from a server-verified booking; join eligibility is a server decision, never a client clock comparison",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Manage session; contact support",
  "fixtureId": "fx.s34-confirmed",
  "layoutFamily": "receipt",
  "a11yObligations": "Confirmed status announced on entry; disabled join exposes aria-disabled plus a text reason; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; masked payment method only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {}
 },
 {
  "index": 26,
  "id": "s34-pending",
  "label": "Pending provider verification (not confirmed)",
  "screen": "S-34",
  "trigger": "Provider event not yet received",
  "requiredInfoActions": "Explicit not-confirmed wording, no join action, what happens next",
  "category": "confirmation",
  "serverAuthoritativeRule": "Confirmation is rendered only from a server-verified booking; join eligibility is a server decision, never a client clock comparison",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Manage session; contact support",
  "fixtureId": "fx.s34-pending",
  "layoutFamily": "receipt",
  "a11yObligations": "Confirmed status announced on entry; disabled join exposes aria-disabled plus a text reason; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; masked payment method only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "pending"
  }
 },
 {
  "index": 27,
  "id": "s34-join-early",
  "label": "Join disabled before window",
  "screen": "S-34",
  "trigger": "Student opens confirmation before the join window",
  "requiredInfoActions": "Disabled join with the reason and the exact opening time",
  "category": "confirmation",
  "serverAuthoritativeRule": "Confirmation is rendered only from a server-verified booking; join eligibility is a server decision, never a client clock comparison",
  "typedError": "JOIN_NOT_YET_OPEN (PROPOSED label)",
  "recovery": "Wait for the join window; set a reminder",
  "fixtureId": "fx.s34-join-early",
  "layoutFamily": "receipt",
  "a11yObligations": "Confirmed status announced on entry; disabled join exposes aria-disabled plus a text reason; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; masked payment method only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "join-early"
  }
 },
 {
  "index": 28,
  "id": "s34-join-open",
  "label": "Join window open",
  "screen": "S-34",
  "trigger": "Current time enters the join window",
  "requiredInfoActions": "Enabled join, device-test entry, remaining time to start",
  "category": "confirmation",
  "serverAuthoritativeRule": "Confirmation is rendered only from a server-verified booking; join eligibility is a server decision, never a client clock comparison",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Manage session; contact support",
  "fixtureId": "fx.s34-join-open",
  "layoutFamily": "receipt",
  "a11yObligations": "Confirmed status announced on entry; disabled join exposes aria-disabled plus a text reason; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; masked payment method only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "join-open"
  }
 },
 {
  "index": 29,
  "id": "s34-reminders",
  "label": "Reminder schedule",
  "screen": "S-34",
  "trigger": "Student opens the reminders disclosure",
  "requiredInfoActions": "Reminder offsets, channel, opt-out route",
  "category": "confirmation",
  "serverAuthoritativeRule": "Confirmation is rendered only from a server-verified booking; join eligibility is a server decision, never a client clock comparison",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Manage session; contact support",
  "fixtureId": "fx.s34-reminders",
  "layoutFamily": "receipt",
  "a11yObligations": "Confirmed status announced on entry; disabled join exposes aria-disabled plus a text reason; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; masked payment method only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "reminders"
  }
 },
 {
  "index": 30,
  "id": "s34-receipt",
  "label": "Receipt / reference detail",
  "screen": "S-34",
  "trigger": "Student opens the receipt disclosure",
  "requiredInfoActions": "Amount paid, method (masked), payment reference, booking reference, download",
  "category": "confirmation",
  "serverAuthoritativeRule": "Confirmation is rendered only from a server-verified booking; join eligibility is a server decision, never a client clock comparison",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Manage session; contact support",
  "fixtureId": "fx.s34-receipt",
  "layoutFamily": "receipt",
  "a11yObligations": "Confirmed status announced on entry; disabled join exposes aria-disabled plus a text reason; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; masked payment method only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "receipt"
  }
 },
 {
  "index": 31,
  "id": "s35-upcoming",
  "label": "Upcoming session management",
  "screen": "S-35",
  "trigger": "Student opens the session from Sessions",
  "requiredInfoActions": "Session identity, time, join eligibility, cancel/reschedule entry, refund eligibility summary",
  "category": "session-management",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "n/a — nominal state",
  "fixtureId": "fx.s35-upcoming",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {}
 },
 {
  "index": 32,
  "id": "s35-policy",
  "label": "Policy preview before action",
  "screen": "S-35",
  "trigger": "Student opens cancel or reschedule",
  "requiredInfoActions": "Exact policy outcome for this session before any destructive action, cutoff time",
  "category": "session-management",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Back without acting",
  "fixtureId": "fx.s35-policy",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "policy"
  }
 },
 {
  "index": 33,
  "id": "s35-cancel-eligible",
  "label": "Cancel ≥24h — full refund",
  "screen": "S-35",
  "trigger": "Cancel requested more than 24h before start",
  "requiredInfoActions": "Eligibility, full amount, masked destination, timing, confirm/keep actions",
  "category": "refund",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Keep session",
  "fixtureId": "fx.s35-cancel-eligible",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund"
  }
 },
 {
  "index": 34,
  "id": "s35-cancel-late",
  "label": "Cancel <24h — admin exception",
  "screen": "S-35",
  "trigger": "Cancel requested inside the 24h window",
  "requiredInfoActions": "No-automatic-refund wording, exception request route, no dark pattern",
  "category": "refund",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "CANCELLATION_WINDOW_CLOSED (PROPOSED label)",
  "recovery": "Request an admin exception; keep session",
  "fixtureId": "fx.s35-cancel-late",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "late"
  }
 },
 {
  "index": 35,
  "id": "s35-tutor-cancelled",
  "label": "Tutor cancelled — full refund",
  "screen": "S-35",
  "trigger": "Tutor cancels the session",
  "requiredInfoActions": "Tutor-initiated wording, automatic full refund, rebooking route",
  "category": "refund",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Rebook with the same or another tutor",
  "fixtureId": "fx.s35-tutor-cancelled",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "tutor-cancelled"
  }
 },
 {
  "index": 36,
  "id": "s35-reschedule",
  "label": "Free reschedule — slot pick",
  "screen": "S-35",
  "trigger": "Student chooses reschedule inside the free window",
  "requiredInfoActions": "New slot list, payment preserved wording, confirm action",
  "category": "session-management",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Back to session",
  "fixtureId": "fx.s35-reschedule",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "reschedule"
  }
 },
 {
  "index": 37,
  "id": "s35-confirm-modal",
  "label": "Destructive confirmation modal",
  "screen": "S-35",
  "trigger": "Student triggers cancel and refund",
  "requiredInfoActions": "Exact amount, destination, irreversibility, explicit confirm and dismiss",
  "category": "session-management",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Dismiss returns focus to the invoker",
  "fixtureId": "fx.s35-confirm-modal",
  "layoutFamily": "manage",
  "a11yObligations": "role=dialog + aria-modal, focus moved into dialog, ESC returns focus to invoker; Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "overlay": "dialog"
  }
 },
 {
  "index": 38,
  "id": "s35-refund-requested",
  "label": "Refund requested",
  "screen": "S-35",
  "trigger": "Confirmation accepted",
  "requiredInfoActions": "Request acknowledged, reference, progress step 1, expected timing",
  "category": "refund",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Track progress",
  "fixtureId": "fx.s35-refund-requested",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "req"
  }
 },
 {
  "index": 39,
  "id": "s35-refund-processing",
  "label": "Refund processing",
  "screen": "S-35",
  "trigger": "Provider accepted the refund request",
  "requiredInfoActions": "Progress step, provider stage, no success claim",
  "category": "refund",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Wait; contact support after the window",
  "fixtureId": "fx.s35-refund-processing",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "proc"
  }
 },
 {
  "index": 40,
  "id": "s35-refund-succeeded",
  "label": "Refund succeeded",
  "screen": "S-35",
  "trigger": "Server receives the verified refund settlement event",
  "requiredInfoActions": "Settled amount, destination, settlement date, receipt",
  "category": "refund",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Download receipt",
  "fixtureId": "fx.s35-refund-succeeded",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "ok"
  }
 },
 {
  "index": 41,
  "id": "s35-refund-failed",
  "label": "Refund failed — retry",
  "screen": "S-35",
  "trigger": "Provider rejects or times out the refund",
  "requiredInfoActions": "Typed failure, money-safe wording, retry action, support route",
  "category": "refund",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "REFUND_FAILED (PROPOSED label)",
  "recovery": "Safe retry with the same refund reference",
  "fixtureId": "fx.s35-refund-failed",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "fail"
  }
 },
 {
  "index": 42,
  "id": "s35-refund-review",
  "label": "Refund — manual review",
  "screen": "S-35",
  "trigger": "Refund routed to manual review",
  "requiredInfoActions": "Review explanation, expected turnaround, reference, contact route",
  "category": "refund",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "REFUND_MANUAL_REVIEW (PROPOSED label)",
  "recovery": "Wait for resolution; contact support",
  "fixtureId": "fx.s35-refund-review",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "review"
  }
 },
 {
  "index": 43,
  "id": "s35-conflict",
  "label": "Stale action / concurrent change",
  "screen": "S-35",
  "trigger": "The session changed after the page was loaded",
  "requiredInfoActions": "Stale-view explanation, what changed, refresh action, no silent overwrite",
  "category": "session-management",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "STALE_STATE (PROPOSED label)",
  "recovery": "Refresh to the current server state",
  "fixtureId": "fx.s35-conflict",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "conflict"
  }
 },
 {
  "index": 44,
  "id": "s35-already-started",
  "label": "Session already started/ended",
  "screen": "S-35",
  "trigger": "Action attempted after the session start",
  "requiredInfoActions": "Time-based refusal, what is still possible",
  "category": "session-management",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "SESSION_ALREADY_STARTED (PROPOSED label)",
  "recovery": "Go to the session or to attendance",
  "fixtureId": "fx.s35-already-started",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "started"
  }
 },
 {
  "index": 45,
  "id": "s35-offline",
  "label": "Offline / provider failure — safe retry",
  "screen": "S-35",
  "trigger": "Network offline or a backing service fails",
  "requiredInfoActions": "Offline/failure explanation, nothing lost, safe retry",
  "category": "session-management",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NETWORK_UNAVAILABLE (PROPOSED label)",
  "recovery": "Retry when back online",
  "fixtureId": "fx.s35-offline",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "refund",
   "extra": "offline"
  }
 },
 {
  "index": 46,
  "id": "s35-prejoin",
  "label": "Pre-join identity + device test entry",
  "screen": "S-35",
  "trigger": "Student opens Join from S-34 or S-35",
  "requiredInfoActions": "Session identity, device-test entry, join action, privacy note",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Run the device test",
  "fixtureId": "fx.s35-prejoin",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-prejoin"
  }
 },
 {
  "index": 47,
  "id": "s35-devices",
  "label": "Device check — preview + selectors",
  "screen": "S-35",
  "trigger": "Student runs the device test",
  "requiredInfoActions": "Self preview, camera and microphone selectors, level indication, retest",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Change device and retest",
  "fixtureId": "fx.s35-devices",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-devices"
  }
 },
 {
  "index": 48,
  "id": "s35-perm-cam",
  "label": "Camera permission denied",
  "screen": "S-35",
  "trigger": "Browser camera permission denied",
  "requiredInfoActions": "Denied explanation, per-browser recovery steps, audio-only alternative",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "MEDIA_PERMISSION_DENIED_CAMERA (PROPOSED label)",
  "recovery": "Grant permission and retest; join audio-only",
  "fixtureId": "fx.s35-perm-cam",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-perm-cam"
  }
 },
 {
  "index": 49,
  "id": "s35-perm-mic",
  "label": "Microphone denied",
  "screen": "S-35",
  "trigger": "Browser microphone permission denied",
  "requiredInfoActions": "Denied explanation, recovery steps, consequence of joining without audio",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "MEDIA_PERMISSION_DENIED_MICROPHONE (PROPOSED label)",
  "recovery": "Grant permission and retest",
  "fixtureId": "fx.s35-perm-mic",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-perm-mic"
  }
 },
 {
  "index": 50,
  "id": "s35-perm-pending",
  "label": "Permission dismissed / pending",
  "screen": "S-35",
  "trigger": "Permission prompt dismissed without a decision",
  "requiredInfoActions": "Neutral pending wording, prompt-again action",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "MEDIA_PERMISSION_DISMISSED (PROPOSED label)",
  "recovery": "Ask again",
  "fixtureId": "fx.s35-perm-pending",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-perm-pending"
  }
 },
 {
  "index": 51,
  "id": "s35-no-device",
  "label": "No camera/microphone found",
  "screen": "S-35",
  "trigger": "No input device enumerated",
  "requiredInfoActions": "Missing-device explanation, connect-and-retest action",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "MEDIA_DEVICE_NOT_FOUND (PROPOSED label)",
  "recovery": "Connect a device and retest",
  "fixtureId": "fx.s35-no-device",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-no-device"
  }
 },
 {
  "index": 52,
  "id": "s35-device-busy",
  "label": "Device busy / in use",
  "screen": "S-35",
  "trigger": "Device held by another application",
  "requiredInfoActions": "Busy explanation, close-other-app guidance, retry",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "MEDIA_DEVICE_IN_USE (PROPOSED label)",
  "recovery": "Close the other application and retry",
  "fixtureId": "fx.s35-device-busy",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-device-busy"
  }
 },
 {
  "index": 53,
  "id": "s35-unsupported",
  "label": "Unsupported browser",
  "screen": "S-35",
  "trigger": "Browser lacks the required media capability",
  "requiredInfoActions": "Capability explanation, supported-browser guidance",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "MEDIA_UNSUPPORTED_BROWSER (PROPOSED label)",
  "recovery": "Open in a supported browser",
  "fixtureId": "fx.s35-unsupported",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-unsupported"
  }
 },
 {
  "index": 54,
  "id": "s35-insecure",
  "label": "Insecure origin",
  "screen": "S-35",
  "trigger": "Page served from a non-secure context",
  "requiredInfoActions": "Secure-context requirement explained without leaking internals",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "MEDIA_INSECURE_CONTEXT (PROPOSED label)",
  "recovery": "Open the secure URL",
  "fixtureId": "fx.s35-insecure",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-insecure"
  }
 },
 {
  "index": 55,
  "id": "s35-constraint",
  "label": "Media constraint failure",
  "screen": "S-35",
  "trigger": "Requested media constraints cannot be satisfied",
  "requiredInfoActions": "Constraint explanation, lower-quality fallback offer",
  "category": "prejoin-device",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "MEDIA_CONSTRAINT_FAILED (PROPOSED label)",
  "recovery": "Retry with a lower quality profile",
  "fixtureId": "fx.s35-constraint",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "device",
   "extra": "s35-constraint"
  }
 },
 {
  "index": 56,
  "id": "s35-join-early-v",
  "label": "Join too early",
  "screen": "S-35",
  "trigger": "Join attempted before the join window",
  "requiredInfoActions": "Server-decided refusal, exact opening time, reminder route",
  "category": "prejoin-eligibility",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "JOIN_NOT_YET_OPEN (PROPOSED label)",
  "recovery": "Wait for the window; set a reminder",
  "fixtureId": "fx.s35-join-early-v",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "eligibility",
   "extra": "s35-join-early-v"
  }
 },
 {
  "index": 57,
  "id": "s35-pay-unverified",
  "label": "Payment not verified",
  "screen": "S-35",
  "trigger": "Join attempted while payment is unverified",
  "requiredInfoActions": "Refusal reason, no join, payment status route",
  "category": "prejoin-eligibility",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "JOIN_PAYMENT_UNVERIFIED (PROPOSED label)",
  "recovery": "Check payment status",
  "fixtureId": "fx.s35-pay-unverified",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "eligibility",
   "extra": "s35-pay-unverified"
  }
 },
 {
  "index": 58,
  "id": "s35-token-expired",
  "label": "Join credential expired",
  "screen": "S-35",
  "trigger": "The short-lived join credential has expired",
  "requiredInfoActions": "Expiry explained without printing the credential, refresh action",
  "category": "prejoin-eligibility",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "JOIN_CREDENTIAL_EXPIRED (PROPOSED label)",
  "recovery": "Request a fresh credential",
  "fixtureId": "fx.s35-token-expired",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "eligibility",
   "extra": "s35-token-expired"
  }
 },
 {
  "index": 59,
  "id": "s35-wrong-user",
  "label": "Wrong user / cross-user access",
  "screen": "S-35",
  "trigger": "Signed-in identity does not own the booking",
  "requiredInfoActions": "Neutral refusal with no information about the other booking",
  "category": "prejoin-eligibility",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "JOIN_FORBIDDEN (PROPOSED label)",
  "recovery": "Switch account; go to my sessions",
  "fixtureId": "fx.s35-wrong-user",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "eligibility",
   "extra": "s35-wrong-user"
  }
 },
 {
  "index": 60,
  "id": "s35-ended",
  "label": "Session already ended",
  "screen": "S-35",
  "trigger": "Join attempted after the session end",
  "requiredInfoActions": "Ended explanation, attendance and review routes",
  "category": "prejoin-eligibility",
  "serverAuthoritativeRule": "Join eligibility, credential lifetime and ownership are decided server-side; the client never grants itself entry. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9 on SAATHI-66/129).",
  "typedError": "JOIN_SESSION_ENDED (PROPOSED label)",
  "recovery": "Go to attendance",
  "fixtureId": "fx.s35-ended",
  "layoutFamily": "prejoin",
  "a11yObligations": "Permission and eligibility outcomes announced via aria-live=assertive for refusals and polite for status; recovery steps are text, not colour; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or join credential is written to URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "eligibility",
   "extra": "s35-ended"
  }
 },
 {
  "index": 61,
  "id": "s35-room-waiting",
  "label": "Room — waiting for tutor",
  "screen": "S-35",
  "trigger": "Student enters the room before the tutor",
  "requiredInfoActions": "Waiting status, elapsed time, full control dock, leave",
  "category": "room-live",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Leave and return",
  "fixtureId": "fx.s35-room-waiting",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "veil": [
    "Waiting for Adv. Meera Krishnan",
    "The room is open. You will see and hear your mentor as soon as they join."
   ]
  }
 },
 {
  "index": 62,
  "id": "s35-room-live",
  "label": "Room — live (tutor + student)",
  "screen": "S-35",
  "trigger": "Both participants are connected",
  "requiredInfoActions": "Remote tile, self view, mic, camera, devices, leave, session details entry",
  "category": "room-live",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "NONE:no error surface in this state",
  "recovery": "n/a — nominal state",
  "fixtureId": "fx.s35-room-live",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {}
 },
 {
  "index": 63,
  "id": "s35-room-muted",
  "label": "Room — participant muted",
  "screen": "S-35",
  "trigger": "Microphone is muted locally or remotely",
  "requiredInfoActions": "Muted state on the control and on the tile, non-colour indication",
  "category": "room-live",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Unmute",
  "fixtureId": "fx.s35-room-muted",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "mic": "off",
   "veil": null
  }
 },
 {
  "index": 64,
  "id": "s35-room-camoff",
  "label": "Room — camera off",
  "screen": "S-35",
  "trigger": "Camera turned off",
  "requiredInfoActions": "Camera-off state on the control and the tile, device released wording",
  "category": "room-live",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Turn camera on",
  "fixtureId": "fx.s35-room-camoff",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "cam": "off"
  }
 },
 {
  "index": 65,
  "id": "s35-autoplay",
  "label": "Audio autoplay blocked",
  "screen": "S-35",
  "trigger": "Browser blocks audio playback until a gesture",
  "requiredInfoActions": "Explicit enable-sound action, reason, keyboard reachable",
  "category": "room-live",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "MEDIA_AUTOPLAY_BLOCKED (PROPOSED label)",
  "recovery": "Activate Enable sound",
  "fixtureId": "fx.s35-autoplay",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "banner": [
    "warn",
    "Sound is blocked by your browser",
    "Choose Enable sound to hear your mentor. Nothing else changes."
   ]
  }
 },
 {
  "index": 66,
  "id": "s35-remote-missing",
  "label": "Remote track unavailable",
  "screen": "S-35",
  "trigger": "Remote media track is absent",
  "requiredInfoActions": "Explanation, audio-only continuation, retry",
  "category": "room-live",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "REMOTE_TRACK_UNAVAILABLE (PROPOSED label)",
  "recovery": "Retry media; continue audio-only",
  "fixtureId": "fx.s35-remote-missing",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "veil": [
    "Mentor video unavailable",
    "Audio is still connected. We are retrying video in the background."
   ]
  }
 },
 {
  "index": 67,
  "id": "s35-degraded",
  "label": "Degraded network",
  "screen": "S-35",
  "trigger": "Connection quality drops",
  "requiredInfoActions": "Quality status, what was reduced, controls unchanged",
  "category": "room-network",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "NETWORK_DEGRADED (PROPOSED label)",
  "recovery": "Continue; switch to audio-only",
  "fixtureId": "fx.s35-degraded",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "banner": [
    "warn",
    "Connection is weak",
    "Video quality was reduced to keep audio clear. Your controls are unchanged."
   ]
  }
 },
 {
  "index": 68,
  "id": "s35-reconnecting",
  "label": "Reconnecting",
  "screen": "S-35",
  "trigger": "Transport temporarily lost",
  "requiredInfoActions": "Reconnect status, elapsed attempt, leave still available",
  "category": "room-network",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "NETWORK_RECONNECTING (PROPOSED label)",
  "recovery": "Wait; leave",
  "fixtureId": "fx.s35-reconnecting",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "veil": [
    "Reconnecting…",
    "We are restoring your connection. Your seat is held and nothing is charged again."
   ],
   "banner": [
    "warn",
    "Reconnecting",
    "Attempt 2. Leave stays available at all times."
   ]
  }
 },
 {
  "index": 69,
  "id": "s35-icefail",
  "label": "ICE/TURN failure — full reconnect",
  "screen": "S-35",
  "trigger": "Media transport cannot be established",
  "requiredInfoActions": "Typed transport failure, full-reconnect action, leave",
  "category": "room-network",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "MEDIA_TRANSPORT_FAILED (PROPOSED label)",
  "recovery": "Rejoin the room",
  "fixtureId": "fx.s35-icefail",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "veil": [
    "Connection could not be established",
    "Your network blocked the media path. Rejoin to try a relayed connection."
   ],
   "banner": [
    "err",
    "Media transport failed",
    "Rejoin to try a relayed path."
   ]
  }
 },
 {
  "index": 70,
  "id": "s35-tutor-left",
  "label": "Tutor left",
  "screen": "S-35",
  "trigger": "Remote participant disconnects",
  "requiredInfoActions": "Who left, what happens next, wait or leave, attendance note",
  "category": "room-live",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "REMOTE_PARTICIPANT_LEFT (PROPOSED label)",
  "recovery": "Wait; leave and go to attendance",
  "fixtureId": "fx.s35-tutor-left",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "veil": [
    "Your mentor left the room",
    "If this was not the end of the session, wait here. Attendance is decided after the scheduled end."
   ]
  }
 },
 {
  "index": 71,
  "id": "s35-leave-confirm",
  "label": "Leave confirmation",
  "screen": "S-35",
  "trigger": "Student activates Leave",
  "requiredInfoActions": "Consequence of leaving, device release note, confirm and stay",
  "category": "room-exit",
  "serverAuthoritativeRule": "Room membership, media authority and session end are server/provider-owned; the client never asserts attendance from room presence. Video provider seam is PENDING_PRIORITY2_CONTRACT (W2-9).",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Stay in the room",
  "fixtureId": "fx.s35-leave-confirm",
  "layoutFamily": "room",
  "a11yObligations": "Room root is a landmark; mic/camera use aria-pressed with a state-carrying accessible name; status changes announced via aria-live=polite; every control >=44x44 and always in the viewport; leave dialog traps focus and restores it; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "No media, device label or credential persisted; leaving releases all local tracks",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "overlay": "leave"
  }
 },
 {
  "index": 72,
  "id": "s35-post",
  "label": "Post-session (tracks released)",
  "screen": "S-35",
  "trigger": "Student leaves or the session ends",
  "requiredInfoActions": "Confirmation that camera and microphone were released, next steps",
  "category": "session-management",
  "serverAuthoritativeRule": "Cancellation eligibility, refund amount and refund lifecycle are computed and settled server-side from the frozen policy; money is integer paise; refunds are idempotent by refund reference",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Go to attendance",
  "fixtureId": "fx.s35-post",
  "layoutFamily": "manage",
  "a11yObligations": "Progress and outcome announced via aria-live=polite; refund status conveyed by text and shape, never colour alone; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; survives reload; masked destination only",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "post"
  }
 },
 {
  "index": 73,
  "id": "s35-att-pending",
  "label": "Attendance pending (after end)",
  "screen": "S-35",
  "trigger": "Scheduled end passes",
  "requiredInfoActions": "Pending explanation, who acts next, expected timing",
  "category": "attendance",
  "serverAuthoritativeRule": "Attendance/completion authority is PENDING_PRIORITY2_CONTRACT (W2-6 on SAATHI-65/66) — this reference states the UI obligation only and must not be read as an approved API. ",
  "typedError": "ATTENDANCE_PENDING (PROPOSED label)",
  "recovery": "Wait for the tutor mark",
  "fixtureId": "fx.s35-att-pending",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PENDING_PRIORITY2_CONTRACT",
  "delta": {
   "variant": "att",
   "extra": "pending"
  }
 },
 {
  "index": 74,
  "id": "s35-att-marked",
  "label": "Attendance marked by tutor",
  "screen": "S-35",
  "trigger": "Tutor submits an attendance mark",
  "requiredInfoActions": "What was marked, by whom, when, confirm or dispute",
  "category": "attendance",
  "serverAuthoritativeRule": "Attendance/completion authority is PENDING_PRIORITY2_CONTRACT (W2-6 on SAATHI-65/66) — this reference states the UI obligation only and must not be read as an approved API. ",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Confirm or dispute",
  "fixtureId": "fx.s35-att-marked",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PENDING_PRIORITY2_CONTRACT",
  "delta": {
   "variant": "att",
   "extra": "marked"
  }
 },
 {
  "index": 75,
  "id": "s35-att-confirm",
  "label": "Student confirmed attendance",
  "screen": "S-35",
  "trigger": "Student confirms the mark",
  "requiredInfoActions": "Confirmation record, unlocked review route",
  "category": "attendance",
  "serverAuthoritativeRule": "Attendance/completion authority is PENDING_PRIORITY2_CONTRACT (W2-6 on SAATHI-65/66) — this reference states the UI obligation only and must not be read as an approved API. ",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Leave a review",
  "fixtureId": "fx.s35-att-confirm",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PENDING_PRIORITY2_CONTRACT",
  "delta": {
   "variant": "att",
   "extra": "confirm"
  }
 },
 {
  "index": 76,
  "id": "s35-att-dispute",
  "label": "Student dispute + reason",
  "screen": "S-35",
  "trigger": "Student disputes the mark",
  "requiredInfoActions": "Reason input with limits, evidence-free wording, submit and cancel",
  "category": "attendance",
  "serverAuthoritativeRule": "Attendance/completion authority is PENDING_PRIORITY2_CONTRACT (W2-6 on SAATHI-65/66) — this reference states the UI obligation only and must not be read as an approved API. ",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Submit or cancel the dispute",
  "fixtureId": "fx.s35-att-dispute",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PENDING_PRIORITY2_CONTRACT",
  "delta": {
   "variant": "att",
   "extra": "dispute"
  }
 },
 {
  "index": 77,
  "id": "s35-att-resolution",
  "label": "Pending admin resolution",
  "screen": "S-35",
  "trigger": "Dispute submitted",
  "requiredInfoActions": "Case reference, expected turnaround, no further student action",
  "category": "attendance",
  "serverAuthoritativeRule": "Attendance/completion authority is PENDING_PRIORITY2_CONTRACT (W2-6 on SAATHI-65/66) — this reference states the UI obligation only and must not be read as an approved API. ",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Wait for resolution",
  "fixtureId": "fx.s35-att-resolution",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PENDING_PRIORITY2_CONTRACT",
  "delta": {
   "variant": "att",
   "extra": "resolution"
  }
 },
 {
  "index": 78,
  "id": "s35-att-resolved",
  "label": "Dispute resolved",
  "screen": "S-35",
  "trigger": "Admin resolves the dispute",
  "requiredInfoActions": "Outcome, effect on refund and review, reference",
  "category": "attendance",
  "serverAuthoritativeRule": "Attendance/completion authority is PENDING_PRIORITY2_CONTRACT (W2-6 on SAATHI-65/66) — this reference states the UI obligation only and must not be read as an approved API. ",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Continue",
  "fixtureId": "fx.s35-att-resolved",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PENDING_PRIORITY2_CONTRACT",
  "delta": {
   "variant": "att",
   "extra": "resolved"
  }
 },
 {
  "index": 79,
  "id": "s35-att-errors",
  "label": "Typed attendance errors (early/dup/unauth/stale)",
  "screen": "S-35",
  "trigger": "Attendance action is invalid",
  "requiredInfoActions": "All four typed refusals visible as distinct text outcomes",
  "category": "attendance",
  "serverAuthoritativeRule": "Attendance/completion authority is PENDING_PRIORITY2_CONTRACT (W2-6 on SAATHI-65/66) — this reference states the UI obligation only and must not be read as an approved API. ",
  "typedError": "ATTENDANCE_TOO_EARLY / ATTENDANCE_DUPLICATE / ATTENDANCE_FORBIDDEN_ROLE / ATTENDANCE_STALE (all PROPOSED labels)",
  "recovery": "Refresh; wait for the scheduled end",
  "fixtureId": "fx.s35-att-errors",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PENDING_PRIORITY2_CONTRACT",
  "delta": {
   "variant": "att",
   "extra": "errors"
  }
 },
 {
  "index": 80,
  "id": "s35-review-blocked",
  "label": "Review locked (no attendance)",
  "screen": "S-35",
  "trigger": "Review opened before confirmed attendance",
  "requiredInfoActions": "Why review is locked, what unlocks it",
  "category": "review",
  "serverAuthoritativeRule": "Review eligibility requires a server-confirmed attendance record; rating and length limits are enforced server-side; moderation is server-owned. ",
  "typedError": "REVIEW_LOCKED_NO_ATTENDANCE (PROPOSED label)",
  "recovery": "Confirm attendance first",
  "fixtureId": "fx.s35-review-blocked",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "review",
   "extra": "blocked"
  }
 },
 {
  "index": 81,
  "id": "s35-review-open",
  "label": "Review form (1–5★, 10–1,000 chars)",
  "screen": "S-35",
  "trigger": "Review unlocked and opened",
  "requiredInfoActions": "Star input 1-5, text 10-1,000 chars with a live counter, moderation notice, submit",
  "category": "review",
  "serverAuthoritativeRule": "Review eligibility requires a server-confirmed attendance record; rating and length limits are enforced server-side; moderation is server-owned. ",
  "typedError": "REVIEW_RATING_OUT_OF_RANGE / REVIEW_TEXT_TOO_SHORT / REVIEW_TEXT_TOO_LONG (all PROPOSED labels)",
  "recovery": "Correct the input and resubmit",
  "fixtureId": "fx.s35-review-open",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "review",
   "extra": "open"
  }
 },
 {
  "index": 82,
  "id": "s35-review-done",
  "label": "Review submitted",
  "screen": "S-35",
  "trigger": "Review accepted for moderation",
  "requiredInfoActions": "Submitted acknowledgement, moderation wording, edit window if any",
  "category": "review",
  "serverAuthoritativeRule": "Review eligibility requires a server-confirmed attendance record; rating and length limits are enforced server-side; moderation is server-owned. ",
  "typedError": "NONE:no error surface in this state",
  "recovery": "Return to sessions",
  "fixtureId": "fx.s35-review-done",
  "layoutFamily": "manage",
  "a11yObligations": "Star input is a labelled radio group reachable by keyboard; the character counter is aria-live=polite; refusals are announced assertively; Visible focus ring on every control; logical DOM order; 44px targets",
  "persistence": "Durable server record; URL-addressable; no free-text narrative echoed into URL, storage or logs",
  "provenance": "PRODUCT_APPROVED",
  "delta": {
   "variant": "review",
   "extra": "done"
  }
 }
];
var BY_ID={};STATES.forEach(function(s){BY_ID[s.id]=s;});
var FAMILIES=['list','profile','checkout','receipt','manage','prejoin','room'];
var API={STATES:STATES,BY_ID:BY_ID,FAMILIES:FAMILIES,IDS:STATES.map(function(s){return s.id;})};
if(typeof module!=='undefined'&&module.exports)module.exports=API;
root.C2States=API;
})(typeof globalThis!=='undefined'?globalThis:this);
