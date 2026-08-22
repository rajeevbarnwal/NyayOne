# NYAY-2 authenticated actor and ownership contract

Status: implementation contract for the consolidated Sprint 1 remediation PR.

## Trust boundary

The server-authenticated actor is the only authority for post-verification
student data. A registration UUID is an identifier, not a bearer capability.
Possession of another registration UUID must not disclose whether that row
exists and must never authorize a read, write, approval, or status transition.

The signup registration UUID may be returned while the account is still
unauthenticated solely to correlate OTP verification and resend requests. OTP
proof, expiry, attempt limits, and the stable registration lock remain the
authority for that bootstrap boundary. Signup-purpose issue, resend, and verify
are valid only while the locked registration remains exactly `otp_pending`.
A successful signup OTP verification rotates an authenticated server-side
session into an HttpOnly cookie and permanently expires that UUID bootstrap;
it cannot be used to reopen OTP delivery or rotate a later session. Every
subsequent student operation derives the registration from that session's
`user_id`; client-supplied registration UUIDs are rejected by schema.

## HTTP decisions

- Missing, forged, expired, revoked, or deleted sessions receive a typed `401`
  on protected endpoints and cause no database change.
- An authenticated non-student actor receives a typed `403` where a student
  role is mandatory.
- A student probing another student's identifier, a missing row, or a
  quarantined DOB row receives the same bounded `404` shape.
- Student academic profile writes, institutional-email requests, and
  verification-status reads resolve the registration from the authenticated
  actor and do not accept a registration UUID in their request contract.
- Guardian-consent approval is privileged work. A student cannot self-approve
  it, including their own registration.
- Student-verification transitions require an admin or legal-reviewer actor.
  Audit evidence records the authenticated reviewer's user ID and role.

## Cookie and browser boundary

Unsafe requests authenticated by the student session cookie require exactly one
trusted HTTP(S) `Origin`, canonicalized for default ports and matched against
the configured allowlist. Missing, malformed, wildcard, userinfo-bearing,
path-bearing, query-bearing, fragment-bearing, null, cross-scheme, cross-host,
or cross-port origins fail before route mutation. Safe methods and pre-auth
requests without the cookie retain their existing behavior.

The browser must not persist a registration UUID in local storage, session
storage, cookies, URLs, service-worker caches, or deterministic globals. A
pre-auth registration attempt may be held only in process memory and is cleared
on authentication, logout, or restart. Reload recovery uses the server session;
it never reconstructs authority from a browser-held UUID.

## Required evidence

The ticket gate must exercise the exact consolidated head with PostgreSQL 16
and independent actors/connections. It must prove:

1. anonymous protected mutations return `401` with an unchanged row/inventory
   digest;
2. actor A cannot observe or mutate actor B through any old UUID-bearing shape;
3. forged, expired, revoked, and deleted sessions have identical no-mutation
   outcomes;
4. guardian self-approval and unprivileged verification transitions fail;
5. an authorized reviewer transition records the real reviewer in audit data;
6. missing, malformed, and untrusted Origins fail before cookie-backed writes;
7. an activated account's former signup UUID cannot issue, resend, verify, or
   deliver another signup OTP and cannot rotate/revoke sessions;
8. browser storage, caches, history, navigation, and deterministic globals
   contain no registration capability; and
9. seeded negative controls that remove ownership, role, Origin, or bootstrap
   status-scope enforcement
   turn the corresponding oracle red.

Evidence must contain bounded outcome codes and aggregate before/after digests,
never raw session cookies, OTPs, mobile numbers, emails, registration UUIDs,
encryption material, or database URLs.
