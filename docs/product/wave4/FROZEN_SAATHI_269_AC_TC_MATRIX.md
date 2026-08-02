# Wave 4 / SAATHI-269 — Frozen AC/TC Matrix

Date: 2026-08-02
Base: `b179766c5fe7f58ae27a3801db0a338b311bc8ca`
Branch: `codex/wave4-private-reporting-saathi-269-274-279`
Product marker: `W4-PRODUCT-APPROVAL-20260801`

This matrix freezes the complete S-86/S-87 production contract before code is
changed. SAATHI-271 remains the local-domain prototype; SAATHI-450 owns the real
FastAPI/PostgreSQL boundary. Browser storage is never the system of record.

## Binding Product and privacy contract

- Privacy modes are `anonymous` and `private_to_platform`; both keep the report
  non-public and ordinary moderators cannot access reporter identity.
- Required fields are organisation, listing/application reference, experience
  start/end dates, category, factual narrative, privacy mode and versioned
  consent.
- Narrative length is 50–5,000 Unicode characters after trimming.
- Categories: unpaid mismatch, excessive hours, unsafe environment, harassment,
  discrimination, misleading/misrepresented work, non-response, certificate
  withheld, stipend delay/exploitative work and positive experience.
- Evidence is PDF/JPEG/PNG, at most five files and 5 MiB per file. Only opaque
  object references and bounded metadata are stored. New evidence is quarantined
  until extension, MIME, signature and malware checks pass.
- Identity is encrypted/key-versioned in a separate vault and matched only with
  a normalized keyed hash. Report projections, logs and audit snapshots never
  carry raw identity, narrative, filenames, evidence contents or secrets.
- Emergency categories show support guidance and cause no automatic employer or
  law-enforcement disclosure.
- `INTERNSHIP_RISK_LABELS_ENABLED=false` is mandatory. S-86/S-87 never expose a
  public allegation or aggregate label.

## Acceptance and executable test matrix

| ID | Requirement | Executable proof |
|---|---|---|
| W4-269-01 | Clean provenance from merged PR #14 | Git HEAD/ancestry/status log |
| W4-269-02 | Forward migration creates the approved report, category, consent, evidence, identity-vault, access-approval, moderation-handoff and outbox structures with UUID/timestamptz/index/FK/check constraints | Alembic upgrade/check/introspection/downgrade/upgrade on PostgreSQL 16; SQLite supplementary |
| W4-269-03 | Create, save and resume an authorised draft through HTTP and a fresh DB session | API integration test plus browser refresh |
| W4-269-04 | Submission requires every binding field, valid date order, 50/5,000 narrative boundary and current consent | Parametrised negative tests; no mutation on failure |
| W4-269-05 | Complete category vocabulary is accepted; unknown categories fail typed and closed | API/schema tests |
| W4-269-06 | Evidence accepts PDF/JPEG/PNG only, rejects 0/6 files, 0 bytes/5 MiB+1, extension/MIME/signature mismatch and scanner failure; state is preserved | Upload API tests with deterministic scanner/storage adapters |
| W4-269-07 | Draft submit is idempotent; duplicate/conflicting idempotency keys cannot duplicate or partially mutate | HTTP replay and conflict tests |
| W4-269-08 | Anonymous, wrong-role and cross-user read/write return non-enumerating 401/403/404 outcomes | Authorisation matrix |
| W4-269-09 | Identity is separated and encrypted; ordinary moderation projections cannot recover it; break-glass requires safety-officer role, reason and two approvals | Model/service/HTTP tests and direct DB privacy scan |
| W4-269-10 | Commit failure and outbox/provider failure roll back or remain durably retryable | Injected transaction/provider failures |
| W4-269-11 | Concurrent save/submit/evidence operations cannot lose updates, exceed five files or duplicate submission | PostgreSQL concurrency tests |
| W4-269-12 | S-86 renders loading, draft, validation, upload/quarantine, retry and success states against the real API; S-87 renders reporter-only status | React/Vitest and Playwright |
| W4-269-13 | Mobile/desktop light/dark at 390/430/768/1024/1440 have no horizontal overflow, 44px targets, working keyboard/focus/ARIA and zero unexpected console/network errors | Headless Chromium screenshots, axe and logs |
| W4-269-14 | Privacy scan finds no raw identity, narrative, filenames, evidence bytes, tokens or secrets in URLs, logs, audit snapshots, browser storage or unauthorised API projections | Fail-closed canary-backed scanner |
| W4-269-15 | Public label flag is false by default and S-86/S-87 cannot publish even when a client forges a request | Config/API/frontend negative tests |
| W4-269-16 | Existing registration, settings, law-school, Wave 2 and Wave 3 gates remain green | Complete backend/frontend regression suites |

## Lifecycle

Implementation tickets remain In Progress until their own native and target
runtime gates pass on the exact pushed commit. Only then may Engineering move
them to Testing. Independent QA owns Testing to In Review. Counsel/Security and
target-runtime approval remain mandatory before public-risk-label activation.
