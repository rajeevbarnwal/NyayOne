# Wave 5 Calendar Interoperability — Frozen Product Contract

Date frozen: 2026-08-02  
Repository base: `adf191dfa6d3229e58e5df0cd8d35f87ad4fb8ae`  
Branch: `codex/wave5-calendar-interoperability-saathi-295`  
Owning epic: SAATHI-284  
Dependency stories: SAATHI-285 and SAATHI-290  
Delivery story: SAATHI-295

This folder is the binding product and verification contract for the Wave 5
calendar vertical slice. It does not contain test results. Every gate remains
`NOT EXECUTED` until an exact-commit artifact is sealed under
`QA/evidence/SAATHI-295/`.

## Authoritative scope

- SAATHI-285 supplies the server-authoritative, user-scoped event aggregate
  used by S-90 and S-91.
- SAATHI-290 supplies server-authoritative reminder preferences used by S-93.
- SAATHI-295 adds S-92 conflict detection and privacy-minimised external
  calendar export, and closes the S-90–S-93 vertical slice.
- SAATHI-286–289, SAATHI-291–294 and SAATHI-296–299 own their frontend,
  service/database, QA and UX parts as mapped in
  `FROZEN_AC_TC_TRACEABILITY.md`.

## Frozen Product decisions

1. This wave delivers RFC 5545/iCalendar (`.ics`) export only. It does not
   claim live Google Calendar, Microsoft Outlook or other OAuth sync.
2. Export capability tokens are cryptographically random 256-bit opaque
   values. Only a keyed hash is stored. Their lifetime is configuration driven
   and defaults to 90 days. They can be rotated and revoked immediately.
3. The raw capability is permitted only in the subscriber URL
   `/api/v1/public/calendar-feeds/{token}.ics`. It is forbidden in application
   logs, audit snapshots, error payloads, browser storage, screenshots and
   sealed evidence. The feed response uses `Referrer-Policy: no-referrer` and
   `Cache-Control: private, no-store`.
4. Calendar data is allowlisted for export. Restricted notes, evidence URLs,
   private database identifiers, enrolment numbers, mobile numbers and email
   addresses are excluded. Event UIDs are pseudonymous and stable only within
   their required scope.
5. Instants are stored in PostgreSQL as UTC `timestamptz`; the user's IANA
   timezone is retained. Conflict detection uses half-open intervals
   `[start_at, end_at)`, so adjacent events are not conflicts.
6. S-90, S-91, S-92 and S-93 use real authenticated APIs and PostgreSQL state.
   Local/session storage is not the system of record.
7. Authentication, ownership isolation, non-enumeration, idempotency,
   concurrency safety, atomic rollback and privacy scans are release gates.
8. Independent QA owns the transition from Testing to In Review. Engineering
   may move a ticket to Testing only after its exact pushed commit passes every
   implementable owned gate.

## Contract documents

- `FROZEN_AC_TC_TRACEABILITY.md` — acceptance criteria, test cases, Jira
  ownership and required evidence paths.
- `NEGATIVE_TEST_MATRIX.md` — explicit boundary, security, privacy, temporal,
  concurrency and rollback cases.
- `PRIVACY_THREAT_MODEL.md` — assets, trust boundaries, threats and required
  controls.
- `QA/evidence/SAATHI-295/FINAL_QA_REPORT_TEMPLATE.md` — fail-closed report
  format to complete only after execution.

## Non-claims

This contract does not assert that APIs, PostgreSQL tables, browser screens,
CI, external calendar subscriptions or Jira lifecycle gates have passed. It
must never be cited as execution evidence.
