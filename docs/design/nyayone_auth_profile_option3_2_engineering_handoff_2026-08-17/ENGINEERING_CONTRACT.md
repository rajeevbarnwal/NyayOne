# NyayOne Option 3.2 engineering contract

## 1. Product outcome

NyayOne lets a student sign in or create an account with minimal friction. Profile completion is optional immediately after authentication. An incomplete user sees a dismissible completion dialog and can finish the profile later from Home or Profile.

The first safe release supports mobile OTP only. Verified-email OTP is part of the approved design, but it remains disabled behind a server-owned, fail-closed feature flag until the backend proves unique verified ownership, non-enumerating responses, safe account binding, and migration integrity.

Existing NyayOne security and privacy controls are a non-regression floor. The stricter rule always wins.

## 2. Visual contract

### Brand assets

Use only the supplied files under `brand/`. Do not redraw, stretch, recolour, or substitute the mark.

- Light desktop and auth header: `brand/lockup/nyayone-lockup.svg`.
- Dark hero or header: `brand/lockup/nyayone-lockup-reversed.svg`.
- Compact mobile header: `brand/mark/nyayone-mark.svg` or the reversed variant.
- One-colour output: `brand/mark/nyayone-mark-mono.svg`.
- PWA and home-screen source: `brand/icons/app-icon.svg`.
- Browser icons: `brand/icons/favicon.svg` and `brand/icons/favicon-16.svg`.

Gold is reserved for the seal and verified states. It is not a decorative background colour.

### Typography

- Display and screen headings declare `Aptos`, `Calibri`, `Carlito`, `system-ui`, `sans-serif` in that order.
- Body, fields, labels, buttons, and supporting text use the existing NyayOne interface sans-serif stack.
- Do not add a serif heading font.
- Do not use faux bold, all-caps hero copy, novelty display faces, or condensed text for form content.
- Automated tests verify the declared approved stack. A computed platform font alone is not proof.

### Iconography

- Use colourful two-tone SVG icons on screen labels, primary actions, profile categories, and status cards where they improve recognition.
- Every decorative SVG has `aria-hidden="true"` and cannot receive focus.
- An icon never replaces the accessible text label.
- Do not use emoji, text glyphs, or unrelated icon styles in the redesigned journey.

### Responsive composition

- Desktop auth uses a calm editorial brand panel and a focused task panel.
- Mobile auth uses a branded top region and a full-width task surface.
- Mobile controls have a minimum interactive size of 44 by 44 CSS pixels.
- There is no horizontal overflow at 360 px, 390 px, or desktop widths.
- At a 390 by 430 keyboard-reduced viewport, the active input and its error remain visible and the primary action remains reachable by scrolling. All fields do not need to fit simultaneously.

### Rebrand boundary

- The redesigned scope contains no visible `LegalSaathi` copy.
- Do not create new `legalsaathi.*` browser-storage keys.
- Any legacy-key migration is explicit, tested, one-time, and never copies credentials or raw PII.

## 3. Canonical route contract

The exact screen map is in `SCREEN_MAP.md`. These rules are mandatory:

- Successful login and signup OTP verification enter S-07.
- S-07 owns the optional profile completion dialog as an overlay state.
- The dialog is not S-14 and has no independent route.
- S-14 remains the full Home dashboard used by application navigation.
- Complete Profile opens the first incomplete server-authoritative profile section.
- Close, Escape, or Maybe Later dismisses the dialog for the current authenticated session and continues to S-14.
- S-14 and S-17 show a persistent completion card while completion is below 100 percent.
- Anonymous direct access to S-07 and S-10 through S-17 redirects to S-03 unless a separately approved public callback contract applies.
- Wrong-role access is rejected. A route guard is not a substitute for backend authorization.

S-10 uses only these allowlisted URL states:

- `/s-10?section=personal`
- `/s-10?section=academic`

S-13 and the backend return a section enum, never an arbitrary URL. Direct entry to a later incomplete section redirects to the first incomplete section or fails closed.

## 4. Authentication and OTP contract

### Passwordless boundary

- S-03 through S-06 contain no password field, password mode, password toggle, or password-auth API request.
- S-06 is passwordless account recovery.
- Passwordless recovery returns to S-04 in the first release.
- A future continuation uses a server-issued allowlisted route enum, never a client-supplied URL.

### S-03 gateway

- Sign In Securely routes to S-04.
- Create Student Account routes to S-08.
- Both controls are real buttons or links with accessible names and visible focus.

### S-04 identifier

- Mobile is the default and only enabled first-release channel.
- Verified email may be displayed as unavailable future capability, but it cannot send an OTP or open S-15 while disabled.
- An anonymous user cannot use S-15 to convert an email address into verified identity.
- A user who wants to enable future email login first authenticates by mobile, saves their own institutional email, then verifies it from the authenticated S-15 flow.
- Enabling verified-email login requires a backend identity contract that proves unique verified ownership before login authority is granted.
- Known, unknown, suspended, and ineligible identifiers receive externally indistinguishable pre-auth responses.
- The selected channel and server-masked destination continue to S-05 without exposing raw identity data in URLs, logs, or browser storage.

### S-05 OTP

- Accept exactly six decimal digits.
- Support paste and platform autofill with `autocomplete="one-time-code"`.
- Blank, short, long, malformed, wrong, expired, reused, locked, and rate-limited codes cannot authenticate.
- Verify and Continue waits for the exact successful server response before navigation.
- Change returns to S-04 with no leaked OTP or credential.
- No raw OTP, session token, bearer, cookie value, mobile, or email appears in evidence.
- Approved masked synthetic destinations may appear in screenshots.
- No fixed sleep or animation timeout proves success.

OTP start and resend responses expose only safe relative metadata:

```json
{
  "status": "accepted",
  "expires_in_seconds": 300,
  "resend_after_seconds": 30,
  "attempts_remaining": 3,
  "challenge_status": "pending",
  "destination_masked": "+91 ..... ..781"
}
```

The client countdown is display-only. Expiry, resend availability, attempt limits, challenge status, locking, and concurrency remain server-authoritative.

### Session creation

Successful login or signup OTP verification atomically:

1. locks and consumes the purpose-bound OTP exactly once,
2. activates or binds the correct student user,
3. revokes or rotates incompatible sessions,
4. creates the server-side session,
5. sets the HttpOnly cookie,
6. returns the onboarding-state projection and no bearer.

Concurrent or replayed verification cannot create a second active session or consume the challenge twice.

## 5. Registration and consent contract

### S-08 account creation

S-08 collects only the approved first-release fields:

- first name,
- optional middle name,
- last name,
- mobile,
- date of birth,
- Terms acceptance,
- Privacy Notice acknowledgement.

Institutional email is collected later in the authenticated academic profile or S-15 flow. It is not an S-08 field.

Required fields are visibly and programmatically required. Legal values are stored separately:

- `terms_accepted`
- `terms_version`
- `privacy_notice_acknowledged`
- `privacy_notice_version`

Missing or false required values produce HTTP 422 with zero registration, OTP, outbox, or audit mutation. Privacy Notice acknowledgement is not described or stored as optional consent.

### Registration anti-enumeration

Registration start always returns the same HTTP 202 status and safe body shape for new, known, duplicate, suspended, and ineligible mobile inputs:

```json
{
  "status": "accepted",
  "next": "otp",
  "expires_in_seconds": 300,
  "resend_after_seconds": 30
}
```

The internal service never overwrites or creates a second identity for a known mobile. Provider behavior, audit detail, and timing cannot become an external account-existence oracle. The UI uses neutral copy and offers Sign In without claiming that an account exists.

### S-09 signup OTP

- Uses the same OTP quality and evidence rules as S-05.
- Successful verification performs the atomic session creation contract in Section 4.
- Successful verification enters S-07 and returns the initial onboarding-state projection.
- Profile completion remains optional.

## 6. Server-authoritative onboarding state

All screens consume one versioned owner-scoped API/read model over normalized database tables. This does not require identity PII, academic data, and interests to share one physical table.

Missing persisted fields require a new forward Alembic revision from the live head. Never edit an applied migration. Do not duplicate identity PII across tables.

The response schema is:

```json
{
  "profile_version": 4,
  "completion_version": "v1",
  "completion_percent": 34,
  "completed_sections": ["personal"],
  "next_incomplete_section": "academic",
  "is_complete": false,
  "institutional_email_status": "not_provided",
  "guardian": {
    "required": false,
    "status": "not_required"
  },
  "access_mode": "full",
  "disabled_capabilities": [],
  "profile_prompt": {
    "should_show": true,
    "dismissed_for_session": false
  }
}
```

Allowed enums:

- section: `personal`, `academic`, `interests`
- institutional email: `not_provided`, `pending`, `verified`, `rejected`, `expired`, `revoked`
- guardian: `not_required`, `required_pending`, `verified`, `rejected`, `revoked`
- access mode: `full`, `limited`

Every profile, guardian, or verification mutation returns this projection or invalidates and immediately refetches it.

### Completion version v1

- Personal is complete when valid first name, last name, preferred language, and city are persisted.
- Academic is complete when valid college, year of study, and enrolment number are persisted.
- Interests is complete when at least one interest and at least one goal are persisted.
- Middle name, photo, pronouns, and Bar enrolment are optional and do not reduce completion.
- Completed sections map deterministically to 0, 34, 67, and 100 percent.
- Every successful profile mutation returns the refreshed calculation.

A new user cannot begin at 67 percent unless the server confirms two complete sections.

## 7. Profile persistence and validation

- S-10 Personal, S-10 Academic, and S-11 Interests use the canonical owner-scoped API/read model.
- Navigation happens only after the corresponding write succeeds.
- Missing session or ownership authority fails closed.
- HTTP 401, 403, 409, 422, 429, 500, network failure, abort, or timeout shows a stable accessible error and retains the form values and route.
- If the server may have committed but the response was interrupted, refetch authoritative state before retrying or navigating.
- Reload and return hydrate from server state. Memory-only draft state is not persistence proof.
- Direct navigation cannot mark an incomplete section complete.
- `profile_version` or an equivalent concurrency token prevents silent multi-tab overwrite. A stale write returns a typed conflict and refreshed state.
- Save and Exit performs a real save before routing to S-14.

Real field values drive validation:

- Legal names follow the exact cross-runtime contract below.
- Date of birth, enrolment, academic, and interest rules match backend schemas.
- Error summaries link to actual inputs and inline errors use `aria-describedby`.
- There is no Mark Fields Corrected or other reviewer/demo bypass.

### Unicode legal-name contract

Frontend, backend, fixtures, and database-facing services apply the same rule:

1. Normalize to Unicode NFC.
2. Trim leading and trailing ASCII space and collapse repeated ASCII spaces to one.
3. Permit Unicode Letter categories, Unicode Mark categories following a Letter or Mark, ASCII space, apostrophe U+0027, left apostrophe U+2018, right apostrophe U+2019, hyphen U+002D, and period U+002E.
4. Reject tabs, line breaks, non-breaking spaces, other whitespace, control characters, symbols, emoji, and all other punctuation.
5. Require at least one Unicode Letter.
6. Enforce 1 through 60 Unicode code points after normalization, trimming, and collapse. JavaScript UTF-16 unit length is not authoritative.

The shared cross-runtime corpus includes at least:

- `Á`, decomposed `A` plus combining acute, and `राज` as valid normalized names,
- `A B`, `O'Neil`, `D’Arcy`, `Anne-Marie`, and `A. Kumar` as valid,
- punctuation-only values, a leading combining mark, `A` plus tab plus `B`, newlines, emoji, and disallowed symbols as invalid,
- 60 and 61 code-point boundaries, including supplementary-plane Unicode letters.

Frontend and backend tests consume the same corpus and assert the same normalized output and decision.

An optional middle name may be absent. When present, it follows the same rule.

## 8. Post-login dialog contract

Profile-prompt dismissal is scoped to the authenticated server session, not only the browser tab. It clears on logout, session rotation, actor change, or session expiry.

S-07 behavior:

- If profile is complete, continue directly to S-14.
- If incomplete and already dismissed for this auth session, continue directly to S-14.
- If incomplete and not dismissed, open the dialog.

The dialog:

- shows the server percentage and next meaningful benefit,
- has Complete Profile, Maybe Later, and close controls,
- moves focus into the dialog,
- traps Tab and Shift+Tab inside the dialog using real keyboard events,
- closes on Escape,
- restores focus to the trigger or a documented safe destination,
- makes the background inert while open,
- writes only non-secret UX state to the server session,
- grants no capability or authorization.

Complete Profile opens the server-supplied first incomplete section. Maybe Later, close, and Escape persist dismissal for that auth session and continue to S-14. S-14 and S-17 retain a completion card until the server reports 100 percent.

## 9. Institutional email and guardian authority

### Institutional email

- S-15 is authenticated-only.
- The student may save and request verification for their own persisted institutional email.
- The student cannot transition the status to verified.
- Verification completion requires an approved purpose-bound proof and server validation.
- An explicit `legal_reviewer` or `admin` actor controls any manual institutional transition.
- Return destinations are a closed enum such as `dashboard`, `profile`, or `profile_completion`.
- An already authenticated user does not return to S-04 unless a server-issued, allowlisted continuation explicitly requires it.

### Guardian state

- The server calculates age and guardian requirements from the persisted date of birth.
- Adult to minor atomically enters `required_pending` and limited access.
- Minor to adult atomically enters `not_required`. It never fabricates verified consent.
- A student cannot self-verify guardian consent.
- Guardian completion remains disabled until Product and Security approve either an authenticated guardian actor or a purpose-bound, expiring, single-use consent-token ceremony.
- PR D may implement restricted-state display and enforcement, but cannot claim guardian completion while the authority ceremony is unresolved.

### Date-of-birth mutation

- An authenticated student may edit date of birth before institutional verification.
- After institutional verification, editing requires step-up authentication and forces identity reverification.
- The write includes `profile_version` and is transactionally coupled to age, guardian, access, and verification-state recalculation.
- Concurrent stale edits fail with a typed conflict.

## 10. Security boundary

- Authentication and ownership derive from a server-side actor context resolved from an HttpOnly session cookie.
- No raw authentication or onboarding bearer is returned to JavaScript or stored in Web Storage.
- Client-supplied registration identifiers are never accepted as ownership authority.
- The session token has at least 256 bits of entropy; only a keyed hash is stored server-side.
- The cookie is HttpOnly, Path `/`, host-only, bounded, SameSite Lax, and Secure outside explicitly local or test environments.
- Cookie-authenticated POST, PUT, PATCH, and DELETE requests require an exact allowlisted Origin. Missing or prefix-matched origins fail closed. CORS uses exact origins and credentialed requests only where required.
- Logout, rotation, completion, revocation, and expiry invalidate the server row and clear the cookie with matching attributes.
- Mobile OTP, email identity, guardian authority, and institutional verification remain independently gated capabilities.
- The visual prototype cannot weaken or replace these controls.
- Production frontend code does not inject actor-claims or test-authentication headers. Non-test runtimes reject them.

Allowed browser storage is fail-closed. Theme, onboarding-seen, and non-secret review preferences may be allowlisted with constrained values. OTPs, identities, cookies, tokens, bearers, registration authority, profile PII, and authorization state are forbidden.

## 11. Implementation prohibition

Do not copy the demo JavaScript, state object, timers, reviewer controls, route aliases, validation shortcuts, or evidence harness from `visual-reference/NYAYONE_OPTION3_2_VISUAL_REFERENCE_ONLY.html`.

Engineers may reuse visual CSS values and compositions only after translating them into NyayOne components, tokens, accessibility primitives, and tested server-backed flows.

Seeded negative tests use disposable fixtures or explicit test-only injection. They never commit or mutate deliberately broken application source.
