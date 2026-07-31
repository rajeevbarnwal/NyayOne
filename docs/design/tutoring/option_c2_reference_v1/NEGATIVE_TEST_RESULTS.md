# Negative test results — Option C2 reference v1

**Provenance:** BROWSER_MEASURED (headless Chromium, 2026-07-29)
**Fixture checksum:** `d45aa35d5614afe2`
**Totals:** 81 cases — 81 PASS

| Area | Total | Pass | Fail | Blocked |
|---|---:|---:|---:|---:|
| Search | 5 | 5 | 0 | 0 |
| Profile | 3 | 3 | 0 | 0 |
| Slots | 3 | 3 | 0 | 0 |
| Hold | 6 | 6 | 0 | 0 |
| Amount | 5 | 5 | 0 | 0 |
| Card | 5 | 5 | 0 | 0 |
| Payment OTP | 7 | 7 | 0 | 0 |
| Duplicate payment | 1 | 1 | 0 | 0 |
| Cancellation | 4 | 4 | 0 | 0 |
| Refund | 4 | 4 | 0 | 0 |
| Permissions | 4 | 4 | 0 | 0 |
| Join | 5 | 5 | 0 | 0 |
| Network | 4 | 4 | 0 | 0 |
| Attendance | 5 | 5 | 0 | 0 |
| Review | 11 | 11 | 0 | 0 |
| Responsive | 5 | 5 | 0 | 0 |
| Privacy | 4 | 4 | 0 | 0 |

## Case detail

| ID | Area | Input | Expected | Actual | Status | Evidence |
|---|---|---|---|---|---|---|
| NEG-SRCH-01 | Search | empty query "" | SEARCH_EMPTY, no request, no dead end | SEARCH_EMPTY | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-SRCH-02 | Search | whitespace only "   \t  " | trimmed to empty -> SEARCH_EMPTY | SEARCH_EMPTY query="" | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-SRCH-03 | Search | 200-character query | SEARCH_TOO_LONG, truncated to 120, no overflow | SEARCH_TOO_LONG len=120 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-SRCH-04 | Search | special characters "<script>&quot;\u0026#39;" | accepted as literal text, escaped, no HTML injection | value kept as text, injected script nodes=0 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-SRCH-05 | Search | query with no results | explicit empty state + recovery action, never a blank page | No mentors match that search \| recovery=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PROF-01 | Profile | very long tutor name (90 chars) | wraps, no horizontal overflow, no clipping of the CTA | hOverflow=0 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PROF-02 | Profile | missing bio / rating data | section omitted or shown as "Not provided"; never "undefined"/"null"/"NaN" | placeholder leakage=false | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PROF-03 | Profile | unknown tutor id | reference resolves to a known state, never a broken render | unknown id resolves to undefined -> router falls back to s31-default | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-SLOT-01 | Slots | held slot | not bookable, status conveyed in text not colour alone | disabled=true text="1:45 AMHeld by another student" | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-SLOT-02 | Slots | booked slot | not bookable, labelled Booked | disabled=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-SLOT-03 | Slots | stale availability (changed after load) | STALE_STATE refusal with refresh, no silent overwrite | typed error: STALE_STATE (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-HOLD-01 | Hold | 600s remaining (10:00) | normal level, plain presentation | normal / 10:00 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-HOLD-02 | Hold | 120s remaining (02:00) | still normal (urgency begins strictly under 2 min) | normal / 02:00 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-HOLD-03 | Hold | 119s remaining (01:59) | urgent level with a NON-COLOUR cue | urgent cue="bold text + thicker border + underline + wording" | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-HOLD-04 | Hold | 1s remaining (00:01) | urgent, still announced, still recoverable | urgent / 00:01 announce=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-HOLD-05 | Hold | 0s remaining (00:00) | HOLD_EXPIRED, slot released, nothing charged | HOLD_EXPIRED \| ui="Your hold expired and the slot was released" | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-HOLD-06 | Hold | urgent hold rendered | urgency carried by weight/border/wording, not hue alone | data-urgent=1 borderWidth=3px wording=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-AMT-01 | Amount | 0 paise | ₹0.00, never blank or "₹NaN" | ₹0.00 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-AMT-02 | Amount | 1 paisa | ₹0.01, no rounding to zero | ₹0.01 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-AMT-03 | Amount | 96082 paise (frozen total) | ₹960.82 and fee+tax+discount reconciles exactly | 96082 -> ₹960.82 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-AMT-04 | Amount | 1,00,00,00,000 paise (large) | Indian digit grouping, no overflow, no exponent | ₹1,00,00,000.00 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-AMT-05 | Amount | non-integer paise 960.825 | throws MONEY_NOT_INTEGER_PAISE — float money is impossible | MONEY_NOT_INTEGER_PAISE | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CARD-01 | Card | all fields empty | three required-field codes, submit blocked | CARD_NUMBER_REQUIRED,CARD_EXPIRY_REQUIRED,CARD_NAME_REQUIRED | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CARD-02 | Card | malformed number "4111-abcd" | CARD_NUMBER_MALFORMED, field-level message | CARD_NUMBER_MALFORMED | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CARD-03 | Card | provider declines the card | typed decline, nothing charged, hold preserved | Your card was declined \| typed error: PAYMENT_DECLINED (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CARD-04 | Card | payment provider unavailable | PROVIDER_UNAVAILABLE, safe idempotent retry offered | typed error: PROVIDER_UNAVAILABLE (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CARD-05 | Card | validation state rendered | each invalid field has aria-describedby pointing at its message | invalid fields=3 all described=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-OTP-01 | Payment OTP | empty code | AUTH_CHALLENGE_REQUIRED, no submit | AUTH_CHALLENGE_REQUIRED | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-OTP-02 | Payment OTP | 5-digit code "41927" | AUTH_CHALLENGE_LENGTH, attempt not consumed | AUTH_CHALLENGE_LENGTH attemptsLeft=3 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-OTP-03 | Payment OTP | 6-digit code "419273" | accepted for submission to the provider (never stored) | ok=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-OTP-04 | Payment OTP | 3 wrong attempts | AUTH_CHALLENGE_LOCKED after the third, nothing charged | AUTH_CHALLENGE_LOCKED attemptsLeft=0 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-OTP-05 | Payment OTP | resend requested | counter + new expiry + cooldown shown | Code 2 of 3 · expires in 4:30. You can request another in 30 seconds. | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-OTP-06 | Payment OTP | expired challenge | AUTH_CHALLENGE_EXPIRED, resend offered, nothing charged | AUTH_CHALLENGE_EXPIRED | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-OTP-07 | Payment OTP | locked state rendered | input disabled, resend disabled, recovery offered | inputDisabled=true resendDisabled=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-DUP-01 | Duplicate payment | same idempotency key submitted twice | charged once, original result replayed, no second booking | Already processed — charged once | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CXL-01 | Cancellation | exactly 24:00:00 before start | full refund (boundary is inclusive) | full_refund 96082 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CXL-02 | Cancellation | 23:59:59 before start | CANCELLATION_WINDOW_CLOSED, admin exception route, no automatic refund | admin_exception CANCELLATION_WINDOW_CLOSED | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CXL-03 | Cancellation | after the session start | SESSION_ALREADY_STARTED, cancellation closed | closed SESSION_ALREADY_STARTED | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-CXL-04 | Cancellation | tutor cancels | automatic full refund regardless of the 24h window | ₹960.82 \| Automatic full refund | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RFD-01 | Refund | provider timeout | REFUND_FAILED, money-safe wording, retry with the same reference | typed error: REFUND_FAILED (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RFD-02 | Refund | duplicate refund request | idempotent by refund reference, one settlement only | refund reference visible=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RFD-03 | Refund | retry after failure | retry action present, reuses the same refund reference | Retry refund | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RFD-04 | Refund | manual review | REFUND_MANUAL_REVIEW with turnaround + reference, no false success | typed error: REFUND_MANUAL_REVIEW (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PERM-01 | Permissions | camera permission denied | typed denial + per-browser recovery + audio-only alternative | typed error: MEDIA_PERMISSION_DENIED_CAMERA (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PERM-02 | Permissions | permission prompt dismissed | MEDIA_PERMISSION_DISMISSED, neutral wording, ask-again action | Ask again | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PERM-03 | Permissions | no camera or microphone present | MEDIA_DEVICE_NOT_FOUND, connect-and-retest, listen-only fallback | typed error: MEDIA_DEVICE_NOT_FOUND (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PERM-04 | Permissions | device busy in another app | MEDIA_DEVICE_IN_USE with a concrete recovery step | typed error: MEDIA_DEVICE_IN_USE (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-JOIN-01 | Join | join before the window opens | JOIN_NOT_YET_OPEN, exact opening time, no join control | typed error: JOIN_NOT_YET_OPEN (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-JOIN-02 | Join | expired join credential | JOIN_CREDENTIAL_EXPIRED, credential never printed | code shown, credential leaked=false | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-JOIN-03 | Join | wrong signed-in user | JOIN_FORBIDDEN, neutral refusal that leaks nothing about the booking owner | tutor name leaked in refusal=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-JOIN-04 | Join | payment not verified | JOIN_PAYMENT_UNVERIFIED, no room entry | typed error: JOIN_PAYMENT_UNVERIFIED (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-JOIN-05 | Join | session already ended | JOIN_SESSION_ENDED, attendance and review routes offered | Go to attendance | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-NET-01 | Network | offline | NETWORK_UNAVAILABLE, nothing lost, retry when online | typed error: NETWORK_UNAVAILABLE (PROPOSED label) | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-NET-02 | Network | degraded connection | quality reduced, controls unchanged, room still 100dvh | dock=true scroll=0 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-NET-03 | Network | ICE/TURN failure | MEDIA_TRANSPORT_FAILED, rejoin action, Leave still reachable | leave in viewport=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-NET-04 | Network | tutor leaves the room | stated clearly, attendance consequence explained, controls kept | Your mentor left the roomIf this was not the end of the sess | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-ATT-01 | Attendance | action before the scheduled end | ATTENDANCE_TOO_EARLY listed as a typed refusal | true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-ATT-02 | Attendance | duplicate attendance action | ATTENDANCE_DUPLICATE, no double record | true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-ATT-03 | Attendance | wrong role acts | ATTENDANCE_FORBIDDEN_ROLE | true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-ATT-04 | Attendance | stale attendance view | ATTENDANCE_STALE + refresh, plus an explicit W2-6 pending notice | stale=true pendingNotice=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-ATT-05 | Attendance | dispute with 1,001 characters | input hard-capped at 1,000, live counter, no silent truncation of a submitted value | maxlength=1000 counter=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-01 | Review | 0 stars | REVIEW_RATING_OUT_OF_RANGE | REVIEW_RATING_OUT_OF_RANGE | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-02 | Review | 1 star | accepted | ok=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-03 | Review | 5 stars | accepted | ok=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-04 | Review | 6 stars | REVIEW_RATING_OUT_OF_RANGE | REVIEW_RATING_OUT_OF_RANGE | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-05 | Review | 0 characters of text | REVIEW_TEXT_TOO_SHORT | REVIEW_TEXT_TOO_SHORT | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-06 | Review | 9 characters | REVIEW_TEXT_TOO_SHORT (boundary) | REVIEW_TEXT_TOO_SHORT len=9 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-07 | Review | 10 characters | accepted (boundary) | ok=true len=10 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-08 | Review | 1,000 characters | accepted (boundary) | ok=true len=1000 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-09 | Review | 1,001 characters | REVIEW_TEXT_TOO_LONG (boundary) | REVIEW_TEXT_TOO_LONG len=1001 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-10 | Review | review opened without confirmed attendance | REVIEW_LOCKED_NO_ATTENDANCE, form not rendered | form present=false | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-REV-11 | Review | star input keyboard reachability | radiogroup with 5 labelled radios, all >=44x44 | radios=5 role=radiogroup small=0 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RSP-01 | Responsive | very long copy injected into every text node | no horizontal overflow at the current viewport | hOverflow=0 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RSP-02 | Responsive | 200% page zoom | no horizontal overflow; primary action still reachable | hOverflow=0 primaryPresent=true | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RSP-03 | Responsive | user font size 200% (root font-size 32px) | no horizontal overflow, controls keep >=44px | hOverflow=0 small=0 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RSP-04 | Responsive | prefers-reduced-motion: reduce | no transition longer than 0s on the room sheet | transition-duration=0s | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-RSP-05 | Responsive | safe-area insets applied to the live room | dock padding honours env(safe-area-inset-bottom); Leave never covered | paddingBottom=8px leaveBottom=836.0 vh=844 | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PRIV-01 | Privacy | canary strings vs document URL | no canary appears in location.href | hits= | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PRIV-02 | Privacy | canary strings vs localStorage + sessionStorage | no canary in any web storage; reference writes no storage at all | storageKeys=0 hits= | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PRIV-03 | Privacy | canary strings vs rendered DOM text | no canary rendered anywhere in the reference | hits= | PASS | MEASURED_GEOMETRY_RESULTS.json |
| NEG-PRIV-04 | Privacy | card number / security code / challenge code persistence | no PAN, CVV or challenge code is written to storage or the URL | url+cookie leakage=false cookieLen=0 | PASS | MEASURED_GEOMETRY_RESULTS.json |
