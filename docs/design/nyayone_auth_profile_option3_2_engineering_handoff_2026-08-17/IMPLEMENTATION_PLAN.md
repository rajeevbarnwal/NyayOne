# NyayOne Option 3.2 implementation plan

Implementation must be split into reviewable vertical slices. Do not combine the visual redesign, email identity, guardian authority, and full security architecture in one pull request.

## PR A: shared visual foundation

- Add official brand assets to the application asset pipeline.
- Add Aptos, Calibri, Carlito, and system UI heading tokens.
- Add the approved SVG icon primitive and two-tone token rules.
- Add auth surfaces, field, error, OTP, dialog, and completion-card primitives.
- Add mobile target and overflow tests.
- Do not change auth behavior in this slice.

## PR B: mobile auth journey

- Redesign S-03, S-04 mobile state, S-05, S-08, and S-09.
- Preserve mobile OTP as the only enabled authentication channel.
- Remove password fields, password mode, password toggles, and password-auth requests from S-03 through S-06.
- Migrate login OTP from legacy S-09 to S-05 and keep S-09 signup-only.
- Make signup OTP consumption, activation, session rotation, HttpOnly cookie creation, and onboarding projection return atomic.
- Add exact cookie, Origin, logout, rotation, replay, ownership, and cross-user tests before UI enablement.
- Implement server-supplied OTP expiry, resend, attempts, status metadata, provider-failure handling, and known-or-unknown response symmetry.
- Implement exact route and response waits.
- Implement versioned Terms acceptance, Privacy Notice acknowledgement, registration anti-enumeration, and negative OTP states.
- Keep verified-email OTP behind a disabled server-controlled feature flag.

## PR C1: owner-scoped profile state foundation

- Add or complete the authenticated owner-scoped profile API.
- Add a new forward migration for missing persisted profile fields. Do not duplicate identity PII.
- Add the versioned onboarding-state projection and completion version v1.
- Add optimistic concurrency, uncertain-result reconciliation, and anonymous, cross-user, forged-UUID, and stale-write tests.
- Keep existing profile UI behavior disabled from using the new contract until these backend gates pass.

## PR C2: optional profile completion UI

- Implement the S-07 dialog state.
- Preserve S-14 as the real dashboard.
- Add S-14 and S-17 completion cards.
- Connect S-10, S-11, S-12, and S-13 to the versioned owner-scoped onboarding-state API/read model.
- Implement fail-closed saves, hydration, resume, and first-incomplete-section routing.
- Scope profile-prompt dismissal to the authenticated server session.

## PR D: guardian and verification alignment

- Implement restricted-state display and the approved server state-machine edges.
- Make adult to minor and minor to adult transitions authoritative.
- Keep student, guardian, and institutional verifier operations separate.
- Implement restricted access, authenticated S-15, and allowlisted return behavior.

This slice cannot invent a guardian or institutional-reviewer identity ceremony. If Product and Security have not approved those authorities, keep positive guardian completion disabled, keep manual institutional verification limited to an explicit approved role, and report the decision blocker. Do not claim S-16 security closure while the guardian ceremony remains unresolved.

## PR E: verified-email OTP

- Start only after unique verified email identity, migration safety, ownership, anti-enumeration, and account-binding rules pass independent review.
- Enable the S-04 verified-email state through a server-controlled feature flag.
- Reuse S-05 presentation while preserving channel-specific server contracts.
- Require the user to verify their own persisted email from an authenticated flow before it can become a login identity.
- Add cross-account, duplicate-email, migration, timing, and evidence privacy tests.

## Required workflow for each PR

1. Branch from the latest NyayOne `origin/main`.
2. Record exact base and head hashes.
3. Keep the changed-file set bounded to the slice.
4. If schema work is required, read the current Alembic head and add a new forward revision. Never edit an applied migration.
5. Run native, target-runtime, accessibility, responsive, privacy, and browser gates applicable to the slice.
6. Push the exact tested commit.
7. Verify local HEAD, remote branch, and PR head equality.
8. Require every NyayOne ruleset context to pass.
9. Obtain independent review before merge.
10. Recheck the prospective merge if main changes.
11. Run and record post-merge main checks.

## Not authorized by this handoff

- Production or external-user enablement.
- Importing LegalSaathi PR 27 through PR 33 as a bulk merge.
- Copying prototype JavaScript.
- Enabling email OTP before identity security closes.
- Treating a design screenshot or prototype measurement as application QA.
