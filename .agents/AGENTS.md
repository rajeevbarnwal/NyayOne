# LegalSaathi Security & Architectural Rule Book

This document defines the architectural boundaries, security invariants, and engineering rules across all **Waves** implemented in the LegalSaathi codebase.

---

## 🏛️ System Wave Architecture Overview

| Wave | Domain & Features | Primary Jira Epic / Stories | Database Models & Migrations |
|---|---|---|---|
| **Wave 0** | Core Auth, OTP Outbox, 3-Step Recovery & Onboarding | `SAATHI-366`, `SAATHI-421`, `SAATHI-448` | `registration.py` (`0001` - `0003`, `0010`) |
| **Wave 1** | Foundation Schema, DPDP Settings, Law School Slice | `SAATHI-58`, `SAATHI-63`, `SAATHI-109/449` | `wave1.py` (`0004` - `0006`) |
| **Wave 2** | Tutoring Marketplace & Server-Authoritative Pricing | `SAATHI-65/66`, `SAATHI-123/127`, `SAATHI-129` | `wave2.py` (`0008`, `0009`) |
| **Wave 3** | Credential-Trust & Identity Verification | `SAATHI-253`, `SAATHI-258` | `credentials.py` (`0007`) |
| **Wave 4** | Private Internship Reporting & Internal Moderation | `SAATHI-269`, `SAATHI-274`, `SAATHI-279` | `wave4.py` (`0011`, `0012`) |
| **Wave 5** | Calendar Interoperability & External Sync | `SAATHI-295` | `0013_wave5_calendar_interop` (Pending Branch) |

---

## 1. Wave 0 Boundaries: Core Security, Anti-Enumeration & Actor Ownership

- **No Pre-Auth UUID Leakage (Anti-Account Enumeration):** Pre-authentication endpoints (`/check-mobile`, `/check-email`, `/recovery/start`) MUST NEVER return database primary keys, internal user IDs, or `registration_id` UUIDs. They must return strictly non-sensitive booleans (`{"exists": bool, "registered": bool}`) or opaque recovery handles.
- **Strict Session-Cookie Actor Ownership:** Every mutation route (`PATCH /profile`, `POST /guardian-consent/complete`, `GET/POST /verification/status`) must validate actor ownership against the authenticated HTTP session cookie (`AuthSession.actor_id == target_user_id`). Accepting raw body or URL UUIDs without session-cookie validation is strictly prohibited.
- **Single-Use Password Reset Lifecycle:** Password recovery MUST use single-use tokens and execute password updates in a single atomic transaction. Calling completion endpoints twice or displaying unfulfilled "Save Password" UI is forbidden.
- **Database Concurrency & Expiry Re-Verification:** Mutative state updates (recovery completion, OTP verification) MUST use `with_for_update()` row locks on SQLAlchemy queries and explicitly re-verify `expires_at > now` inside the locked transaction.
- **DPDP Affirmative Consent Defaults:** Legal consent and privacy checkboxes in UI components MUST default to `false` (unchecked). Pre-checking legal/privacy checkboxes is strictly prohibited under DPDP rules.
- **Strict Input Validation Boundaries:** Never silently manipulate or truncate user inputs (such as `digits[-10:]`). Enforce exact validation regex boundaries (such as `^\d{10}$`, `^\d{6}$`).

---

## 2. Wave 1 Boundaries: DPDP Settings & Law School Catalog

- **Data Subject Rights (DSR) & Optimistic Locking:** `UserSettings` and `PrivacyPreference` support `export` and `delete` (anonymize vs hard delete). `UserSettings` MUST maintain an optimistic concurrency `version` integer counter.
- **Config-Driven Law School Bounds:** Comparison set size limits and ranking thresholds MUST remain config-driven; never bake static numerical limits into Alembic DDL constraints.
- **Selector & Accessibility Parity:** UI form field labels (`label=...`) must match Playwright `getByLabel` selectors exactly (e.g. `"College / University"`, `"Year of study"`, `"College enrolment number"`).

---

## 3. Wave 2 Boundaries: Tutoring Marketplace & Server-Authoritative Pricing

- **Server-Authoritative Money & Pricing:** All monetary values MUST be stored as `INTEGER PAISE` (never float or decimal on the money path). Session pricing is strictly server-authoritative (`tutor_profiles.session_price_paise` copied to immutable `booking_holds.price_paise`). Clients cannot propose price amounts.
- **Positivity CHECK Constraints:** Price columns carry named `> 0` CHECK constraints in database DDL. Zero is not free tutoring; free offerings require explicit product flags.
- **LiveKit/TURN Video Safety:** Video session grants require verified attendance or a valid active `booking_hold`. No client-authoritative attendance overrides or bypasses.

---

## 4. Wave 3 Boundaries: Credential-Trust & Zero-Evidence Storage

- **Zero Evidence Bytes in Database:** PostgreSQL stores ONLY opaque S3/object store references, scan metadata, and keyed hashes (`keyed_hash()`). Raw document evidence bytes MUST NEVER be stored in PostgreSQL.
- **Opaque Verification Tokens:** Verification tokens store keyed hashes, never plain bearer tokens. Every foreign key is indexed and carries explicit `ON DELETE` cascade/set null rules.

---

## 5. Wave 4 Boundaries: Private Internship Reporting & Anonymity

- **Physical Reporter Identity Separation:** Reporter identity is physically separated from report content in `ReporterIdentityVault`. `InternshipReport` tables contain NO user IDs, emails, mobiles, or reversible identity markers. Identity resolution requires encrypted vault access with explicit approval gates.
- **Structural Public Projection Gates:** Public aggregate reporting projections remain structurally disabled until safety and moderation verification gates pass.

---

## 6. Wave 5 & Database Migration Graph Protocol

- **Single Linear Alembic Migration Graph:** Always verify `alembic heads` reports exactly ONE single head. Migration files across feature branches must be linearly ordered (e.g., renumbering local branch migrations to `0014_student_profile_preferences.py`). Parallel branch creation off past heads is strictly prohibited.
- **Dynamic Alembic Head Resolution:** Never hardcode Alembic migration revision strings (e.g. `"0012_wave4_moderation"`, `"0013_student_profile_preferences"`) in test files or gate scripts (`wave2_postgres_gate.py`, `wave4_postgres_gate.py`). Always resolve the latest head revision dynamically via `_expected_alembic_head()`.

---

## 7. Mandatory Verification Protocol

Before pushing any commit to a remote feature branch or pull request:
1. `npm run typecheck` in `frontend/` (0 errors)
2. `npm run test:run` in `frontend/` (665/665 Vitest tests pass)
3. `pytest` in `backend/`
