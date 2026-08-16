# NyayOne auth and profile canonical screen map

This map replaces the conflicting S-07 and S-14 labels inside the Claude prototype.

| ID | Canonical purpose | Entry | Successful exit |
|---|---|---|---|
| S-01 | Session boot probe | App launch | Authenticated to S-07, anonymous to S-02 or S-03 |
| S-02 | Optional product onboarding | First anonymous launch | S-03 |
| S-03 | NyayOne gateway | Public app entry | Sign in to S-04, create account to S-08 |
| S-04 | Login identifier | S-03 | Accepted mobile or feature-gated verified email to S-05 |
| S-05 | Login OTP | S-04 | Successful server verification to S-07 |
| S-06 | Passwordless account recovery | S-04 recovery action | Successful recovery to S-04 |
| S-07 | Authenticated landing and profile-dialog host | S-05 or S-09 | Complete Profile to S-10, dismiss to S-14 |
| S-08 | Student account creation | S-03 | Accepted registration to S-09 |
| S-09 | Signup OTP | S-08 | Successful server verification to S-07 |
| S-10 | Personal and academic profile steps | S-07, S-13, S-14, or S-17 | Next incomplete step or S-11 |
| S-11 | Interests profile step | S-10 or S-13 | S-12 after successful persistence |
| S-12 | Profile details complete | Final successful profile save | S-14 or S-17 |
| S-13 | Resume profile setup | S-14 or S-17 | Server-selected first incomplete step |
| S-14 | Full Home dashboard | S-07 dismissal, application Home navigation | Feature routes or S-17 |
| S-15 | Authenticated institutional email verification | Authenticated academic profile, S-12, S-14, or S-17 | Return to an allowlisted authenticated origin with server state |
| S-16 | Guardian-required limited access | Server guardian policy | S-14 limited state or authorized guardian flow |
| S-17 | Profile view and completion entry | Application Profile navigation | S-13 or direct server-selected incomplete step |

## Overlay rule

The post-login profile completion prompt is an overlay owned by S-07. It is not `S-14p`, S-14, or a separately addressable screen.

## Journey rules

### Returning mobile user

`S-03 -> S-04 -> S-05 -> S-07 -> S-14`

If incomplete, S-07 opens the dialog. Complete Profile goes to S-10. Dismissal goes to S-14.

### New student

`S-03 -> S-08 -> S-09 -> S-07`

Profile completion remains optional after authentication. The same S-07 dialog applies.

### Verified email user

`S-03 -> S-04 -> S-05 -> S-07`

This route remains disabled until verified-email identity is unique, secure, and non-enumerating.

S-15 is not an anonymous bridge from S-04. Before verified-email login is enabled, the user authenticates by mobile and verifies their own persisted institutional email from an authenticated flow.

### Profile completion

`S-07 or S-13 or S-17 -> S-10 Personal -> S-10 Academic -> S-11 Interests -> S-12`

The server may skip a persisted complete step, but the client cannot declare a step complete.

### Guardian-restricted user

`S-10 DOB response -> S-16 limited access`

Only server authority may release the restriction.

## Existing route compatibility

The baseline repository already maps S-07 to `V34VerifiedHome`, S-14 to `Dashboard`, and Home navigation to `/s-14`. The implementation must preserve that public contract while redesigning the components.

## Route migration rules

- The baseline currently maps S-05 to a login-failure component. Option 3.2 reassigns S-05 to login OTP. Wrong, expired, locked, and provider-failure presentations become states inside S-05, not a separate route.
- The baseline currently uses S-09 for both login and signup OTP. Option 3.2 narrows S-09 to signup OTP. Login OTP moves to S-05.
- S-06 remains the route ID for account recovery, but all password UI and password-auth behavior are retired.
- Old bookmarked or internal login-OTP links to S-09 must migrate through an allowlisted route decision. They cannot infer signup authority from the URL.
- Route tests cover every old-to-new mapping and prove that S-07 and S-14 retain their canonical responsibilities.
