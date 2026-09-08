# NYAY-12 verified-email identity and email OTP login contract

Status: implemented by PR E (`codex/nyay12-verified-email-identity`), policy version `nyay12-email-identity-policy.v1`.
Precedence: the Option 3.2 engineering handoff (`docs/design/nyayone_auth_profile_option3_2_engineering_handoff_2026-08-17/ENGINEERING_CONTRACT.md` §4, §9, §10) and the existing NYAY-2/3/4/5/9/11 security floor win over anything here.

## 1. Identity policy (documented, provider-agnostic)

1. Normalize to Unicode NFC, trim ASCII whitespace, apply full Unicode `casefold` to the whole address.
2. Shape: exactly one `@`, a non-empty local part, a domain with at least one dot and a final label of two or more characters, no whitespace, at most 254 code points after normalization.
3. **No plus-tag stripping, dot removal or provider-specific canonicalization.** `first+tag@example.edu` and `first@example.edu` are distinct identities. Any change to this rule is a new policy version and an owner decision.
4. Consumer domains are not rejected for login identities (a login identity is independent of the institutional-email review proof of NYAY-11, which keeps its own allow-list). This is recorded as assumption A-03 for owner confirmation.
5. Uniqueness is enforced in PostgreSQL on the keyed hash of the normalized address:
   * `uq_user_email_identities_verified_email` — one **verified** owner per address;
   * `uq_user_email_identities_one_primary_per_user` — one primary identity per user;
   * `uq_user_email_identities_live_owner_email` — one live (pending or verified) claim per user and address.
6. Raw addresses are stored only as keyed hash + Fernet ciphertext; the owner projection returns a mask (`s•••••@example.edu`). Codes are stored only as keyed hashes. No raw email, code or session token is logged.

## 2. Independence and precedence

* Mobile OTP login never creates, verifies or promotes an email identity.
* The NYAY-11 institutional email proof (S-15 review flow) never creates or verifies a login identity. A student who wants email login verifies the address again through the identity API.
* Migration `0025_nyay12_email_identity` creates no identity rows and marks nothing verified. Duplicated live `student_profiles.institutional_email_hash` values are recorded as `legacy_duplicate` reconciliation rows (hash only) for human review. Downgrade refuses on a populated graph.
* A verified collision (a second user proves a mailbox already verified by another account) fails closed: the claimant receives `409 email_identity_conflict`, a `verified_collision` reconciliation row (holder and claimant ids, hash only) is written, and no transfer or second verified row ever exists.

## 3. Lifecycle API (authenticated student, exact allowlisted Origin, `Idempotency-Key` required)

| Route | Result |
|---|---|
| `GET /api/v1/auth/student/email-identities` | `{login_channel_enabled, max_identities, identities[]}` |
| `POST …/email-identities {email}` | `202 {status:"accepted", identity}`; same response for a new claim or an existing live claim of the caller |
| `POST …/{id}/verify {code}` | `200 {status:"verified", identity}`; the first verified identity becomes primary |
| `POST …/{id}/resend {}` | `202`; 30 s cooldown, resend budget, code rotation |
| `DELETE …/{id}` | `200 {status:"removed", identity}`; a removed primary is not auto-replaced |
| `POST …/{id}/primary {}` | `200 {status:"primary", identity}`; verified only, exclusive |

Identity projection: `{id, email_masked, state: pending|verified|removed, is_primary, verification: {status: none|pending_delivery|active|failed|expired, expires_in_seconds, resend_in_seconds, attempts_left}}` — relative seconds only.

Idempotency: 16–200 characters of `A–Z a–z 0–9 . _ ~ -`, scoped to actor and operation; exact replay returns the sealed outcome with `Idempotency-Replayed: true`; a different payload under the same key is `409 email_identity_idempotency_conflict`.

Abuse controls: add uses the OTP issue budgets (identity / peer IP / global), resend uses the resend budgets and a per-identity cooldown, verification allows `OTP_MAX_ATTEMPTS` attempts within `OTP_CHALLENGE_TTL_SECONDS`; at most `EMAIL_IDENTITY_MAX_PER_USER` (default 3) live identities per user. All limits are typed (`429 email_identity_rate_limited` with `Retry-After`, `409 email_identity_limit_reached`).

Provider failure: the pending claim is committed before the provider call; without a receipt the challenge is `failed` (`503 email_delivery_unavailable`), the claim stays resendable and never reserves the address against its real owner. A missing provider fails closed before any write.

Prerequisites: identity add, verify and set-primary require `access_mode = full` (guardian prerequisites satisfied); otherwise `403 email_identity_capability_disabled`. Removal is always allowed to the owner.

## 4. Email OTP login (S-04 / S-05)

* Server-owned fail-closed flag `EMAIL_LOGIN_ENABLED` (default false). `GET /api/v1/auth/student/login/channels` projects `{channels:[{channel:"mobile",enabled:true},{channel:"email",enabled:<flag>}]}`; the client renders the mobile-only S-04 whenever the projection is absent or the email channel is disabled.
* `POST /api/v1/auth/student/login/email/start {email}`: flag off → `403 email_login_disabled` for every input; flag on → `202` with the unchanged OTP flow projection (masked email destination, HttpOnly flow cookie) for unknown, pending, verified, removed and suspended addresses alike. Only a verified identity owned by an active student registration issues a real delivery; the registration's login authority (attempts, lockout, resend window) is shared with mobile login.
* Verify, resend, state and cancel reuse `/api/v1/auth/student/otp/*`. The channel is recorded server-side on the flow; the client never supplies it. Resend on an email flow re-checks that the identity is still verified and owned.
* Provider: `EMAIL_OTP_PROVIDER=http` with `EMAIL_OTP_PROVIDER_URL` (HTTPS, idempotent, authenticated) is required outside local/test environments when the flag is on; `capturing` is test-only.

## 5. Erasure, retention and lifecycle disposition (review S1)

* **Anonymise / delete (NYAY-19):** inside the same transaction as the registration scrub, after the OTP → User → AuthSession and NYAY-11 authority boundaries and before the aggregate audit row, the subject's complete email-identity graph is disposed: every identity becomes an unlinkable tombstone (`state=removed`, never primary, no challenge, `email_ct` decrypts only to the retention marker, `email_hash` replaced by a per-row erased digest), sealed idempotency ledger rows are deleted, and reconciliation records lose the erased party's link (a record with no remaining party is resolved with an unlinkable hash). Hard deletion applies the same disposition before the User row is removed, so nothing depends on CASCADE. A mentor DEFER or any later failure leaves the graph untouched (no partial erasure).
* **Owner removal:** `DELETE …/{id}` produces the same tombstone immediately; a removed identity never retains a decryptable address and never reserves the address.
* **Terminal retention:** `RETENTION_DAYS_EMAIL_IDENTITY_TERMINAL` (default 30, bounded 1–36500) purges tombstones (by `removed_at`), ledger rows (by `created_at`) and resolved reconciliation records (by `resolved_at`) through `purge_expired`, reported as aggregate counts `email_identity_tombstones`, `email_identity_mutations`, `email_identity_reconciliations`.
* **Lock order:** the identity service locks the subject registration before the User/session rows (`registration → User → AuthSession → identity rows`), matching retention and NYAY-11, so a concurrent erasure and verification serialize without deadlock; the native gate exercises the barrier-released schedule in both orders.

## 6. Published OpenAPI contract (review S2)

Every lifecycle request body is a required closed model (`EmailBody {email}`, `CodeBody {code ^[0-9]{6}$}`, `EmptyBody {}` for resend/primary, no body for DELETE) and every response is a closed model with published enums: identity `state ∈ {pending, verified, removed}`, `verification.status ∈ {none, pending_delivery, active, failed, expired}`, per-route `status` literals (`accepted`, `verified`, `removed`, `primary`), `channels[].channel ∈ {mobile, email}`, and the documented `EmailLoginStartRequest`. Session/origin dependencies resolve before body validation (auth precedence), and framework 422s on the closed lifecycle route-template set keep `Cache-Control: private, no-store` / `Vary: Cookie`.

## 7. Evidence and scope notes

* Native PostgreSQL 16 + pgvector gate: `backend/tests/nyay12_native_gate.py (executed via tests/test_nyay12_postgres_native.py)` (opt-in `NYAY12_POSTGRES_GATE=1`, exit 78 = BLOCKED). Wiring into `backend/scripts/db_gate.sh` requires a governance change (the gate shell is digest-sealed) and is requested from the owner.
* The default S-04 rendering is unchanged, so the sealed Revision L / NYAY-8 baselines stay authoritative; the enabled email state is proven by NYAY-12 Chromium evidence.
