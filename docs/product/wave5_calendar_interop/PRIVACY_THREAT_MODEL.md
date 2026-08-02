# Wave 5 Calendar Interoperability — Privacy Threat Model

Status: frozen design-time threat model; **no control is claimed executed**.

## Assets and sensitivity

| Asset | Sensitivity | Storage rule |
|---|---|---|
| Calendar events, timestamps and source linkage | Personal behavioural data | User-scoped PostgreSQL rows; UTC instants plus IANA timezone |
| Restricted event narrative/source metadata | Sensitive/private | Never exported; minimum internal projection only |
| Reminder preferences | Personal preference data | User-scoped PostgreSQL; version-safe updates |
| Raw export capability | Authentication secret | Return only at creation/rotation and use only in designated feed URL; never persist raw |
| Export capability hash/version/expiry/status | Security metadata | Keyed hash at rest; access-controlled |
| Audit events | Security record | No raw capability or disallowed event fields |
| Public ICS feed | Capability-protected private projection | Explicit field allowlist and no-store/no-referrer response |

## Trust boundaries

1. Authenticated browser to FastAPI calendar endpoints.
2. FastAPI/service layer to PostgreSQL.
3. Public calendar client to the token-bearing `.ics` route.
4. Service to logging, audit and error-reporting sinks.
5. Test/evidence tooling to screenshots, traces, raw HTTP and sealed artifacts.

## Threats and required controls

| ID | Threat | Control | Verification |
|---|---|---|---|
| T-01 | Cross-user event/preference/export access | Cookie-backed actor, ownership predicate on every query/mutation, non-enumerating response | N-11–N-15 authorisation matrix |
| T-02 | Token theft from database | 256-bit random capability; keyed hash only; key version metadata | DB privacy/introspection scan |
| T-03 | Token leakage through logs/audit/errors/evidence | Central redaction; never interpolate request path/capability; evidence sanitizer and canary | N-27/N-48 fail-closed scanner |
| T-04 | Token leakage through referrer/cache | `Referrer-Policy: no-referrer`; `Cache-Control: private, no-store`; no third-party resource from feed | Header/network assertions |
| T-05 | Long-lived or unrecoverable leaked feed | 90-day configurable default; explicit expiry; immediate rotation/revocation | Boundary and lifecycle tests |
| T-06 | Weak/guessable token | CSPRNG, at least 256 bits, constant-time keyed-hash comparison | Format/entropy and implementation audit |
| T-07 | Event PII disclosed in ICS | Deny-by-default field allowlist, restricted-source projection, pseudonymous UID | Seeded forbidden-field canaries and parsed ICS audit |
| T-08 | UID correlation/reversal | Non-reversible keyed pseudonym, scoped stability | Seeded mapping and non-reversibility audit |
| T-09 | ICS injection or parser confusion | RFC 5545 escaping, UTF-8-safe line folding, content type and independent parser | N-31/N-32 parser round trip |
| T-10 | Enumeration through invalid public capabilities | Uniform non-enumerating outcome for malformed/unknown/expired/revoked/rotated tokens | Response body/status/timing matrix |
| T-11 | Race creates multiple active exports or stale conflicts | Unique constraints, row locking/version checks, transactional mutation | PostgreSQL multi-connection race tests |
| T-12 | Partial commit leaves token/audit/event inconsistent | Single transaction ownership and injected commit-failure rollback | DB before/after rollback matrix |
| T-13 | Browser storage becomes secret/system of record | No capability or authoritative calendar data in local/session storage; refresh from API | Browser storage scan/new-context proof |
| T-14 | Misleading OAuth/provider UI | ICS-only scope; no fake Google/Outlook success; no provider network call | Source/network/UI truthfulness audit |
| T-15 | Excess data in screenshots/traces | Synthetic fixtures, token/path redaction before sealing, artifact scanner | Evidence canary and SHA manifest |

## Export allowlist

The implementation must define an explicit allowlist. At minimum, a VEVENT may
contain the pseudonymous UID, sanitised summary, UTC start/end, timezone where
needed by the chosen RFC 5545 representation, created/updated stamps and a
non-sensitive status/category if Product explicitly maps it. Everything else is
denied by default.

Forbidden fields include raw/internal primary keys, owner IDs, mobile numbers,
email addresses, enrolment identifiers, institutional identifiers, notes,
evidence/document URLs, authentication/session secrets and source payloads.

## Raw-token URL exception

The public subscription URL is the sole exception to “no raw token in a URL”:
`/api/v1/public/calendar-feeds/{token}.ics`. This exception is functional, not
permission to log or persist the URL. Middleware, request logging, access logs,
traces and error handlers must redact the token-bearing segment before output.

## Residual risk and release posture

A bearer feed URL can be copied by a legitimate subscriber. Expiry,
rotation/revocation, minimum projection and no-store/no-referrer reduce but do
not eliminate that risk. The UI must say that anyone holding the subscription
link can read the exported projection until expiry or revocation.

Live OAuth sync, provider token storage, two-way edits and provider webhook
threats are out of scope. Adding them requires a separate Product/privacy
decision and threat-model revision.
