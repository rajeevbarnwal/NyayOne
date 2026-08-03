# LegalSaathi Security & Architectural Rules

## 1. Security & PII Protection Protocol
- **No Pre-Auth UUID Leakage:** Pre-authentication endpoints (such as `/check-mobile`, `/check-email`) must NEVER return database primary keys, internal IDs, or `registration_id` UUIDs. Returning pre-auth UUIDs enables account enumeration and cross-user mutation vectors.
- **Strict Session-Cookie Actor Ownership:** Every mutation route (`PATCH /profile`, `/verification`) must validate actor ownership against the authenticated HTTP session cookie (`AuthSession.actor_id == target_user_id`). Accepting raw body/URL UUIDs without session-cookie validation is strictly forbidden.
- **Single-Use Password Reset Lifecycle:** Password recovery must use single-use tokens and execute password updates in a single atomic transaction with `hash_password()`. Calling completion endpoints twice or displaying unfulfilled "Save Password" UI is prohibited.
- **Database Concurrency & Expiry Re-Verification:** Mutative state updates (recovery completion, OTP verification) must use `with_for_update()` row locks on SQLAlchemy queries and explicitly re-verify `expires_at > now` inside the transaction.

## 2. Strict Input Validation & Data Integrity
- **Strict Regex Validation Boundaries:** Never silently manipulate or truncate user inputs (such as `digits[-10:]`). Enforce exact validation regex boundaries (such as `^\d{10}$`).
- **DPDP Affirmative Consent Defaults:** Legal consent and privacy checkboxes in UI components must default to `false` (unchecked). Pre-checking legal/privacy checkboxes is strictly prohibited under DPDP rules.
- **No Silent API Error Swallowing:** Frontend UI forms (such as S-10) must NEVER swallow API failures or proceed as though saved. They must render typed error alerts and preserve user input.

## 3. Mandatory Audit Workflow
- **Pre-Suggestion Audit:** Before suggesting or implementing any code changes, inspect the authoritative backend route handlers, encryption schemas, Alembic migration chains (`versions/`), and security protocols first.

## 4. Pre-Push CI & Gate Verification Protocol
- **Mandatory Pre-Push Verification:** Before pushing any commit to a remote feature branch or PR, run the local verification suite:
  1. `npm run typecheck` in `frontend/`
  2. `npm run test:run` in `frontend/`
  3. `pytest` in `backend/`
- **Single Linear Alembic Migration Graph:** Always verify `alembic heads` reports exactly ONE single head. Migration files must be linearly ordered (renumbering to `0014_student_profile_preferences.py`). Parallel branch creation from historical heads is prohibited.
- **Dynamic Alembic Head Resolution:** Never hardcode Alembic migration revision strings (e.g. `"0012_wave4_moderation"`, `"0013_student_profile_preferences"`) in test files or PostgreSQL gate scripts (`wave2_postgres_gate.py`, `wave4_postgres_gate.py`). Always resolve the latest head revision dynamically via `_expected_alembic_head()`.
- **E2E Playwright Accessibility & Routing Parity:**
  - Form field labels in UI components (`label=...`) must match Playwright `getByLabel` selectors exactly (e.g. `"College / University"`, `"Year of study"`, `"College enrolment number"`).
  - Multi-step wizard transitions must push corresponding URL query parameters (e.g. `nav('/s-10?step=academic')`) on step progression so Playwright `waitForURL` resolves without timing out.
- **Robust Canary String Matching:** Never use short 4-character strings (like `"4111"`) for credit card canary checks. Always use standard 16-digit test PAN strings (`"4111111111111111"`) to prevent false-positive collisions with random UUID hex strings.
