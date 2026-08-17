# NYAY-3 database cardinality and concurrency contract

Status: **implementation-ready red-baseline contract; no fix migration yet**  
Base: `e91f4febfd0903b79ed8c908fa2a773ddd1bbc3b`  
Runtime authority: PostgreSQL 16 with pgvector

NYAY-16 owns the canonical migration-baseline prerequisite. Until that ticket
establishes the next safe forward-revision point, NYAY-3 must not add or edit an
Alembic revision and must not rewrite any historical migration. This document
and the opt-in characterization gate make the failure modes executable without
crossing that boundary.

## Invariants to enforce

| ID | Database invariant | Exact target mechanism |
|---|---|---|
| DB-OTP-1 | At most one unconsumed OTP challenge exists for one registration and purpose. | PostgreSQL partial unique index `uq_otp_challenges_one_active_per_registration_purpose` on `(registration_id, purpose) WHERE consumed_at IS NULL`. |
| DB-SESSION-1 | At most one session with `status='active'` exists for one user. | PostgreSQL partial unique index `uq_auth_sessions_one_active_per_user` on `(user_id) WHERE status = 'active'`. |
| DB-GUARDIAN-1 | A registration has exactly zero or one guardian-consent row. | Unique constraint `uq_guardian_consents_registration_id` on `registration_id`. Application policy decides whether zero is permitted for an adult; the database rejects two for everyone. |
| DB-VERIFY-1 | A registration has exactly one institutional-verification state row after registration creates it. | Unique constraint `uq_student_verifications_registration_id` on `registration_id`. Missing-row detection remains a service/projection invariant; duplicate rows are a database error. |
| DB-GUARDIAN-2 | The boolean and finite-domain status cannot contradict each other. | Check constraint `ck_guardian_consents_verified_matches_status`: `(status = 'verified' AND verified) OR (status IN ('pending', 'sent', 'rejected') AND NOT verified)`. Both columns remain `NOT NULL`. |

`expires_at` is deliberately not part of either partial-index predicate. A row
does not stop being authoritative merely because wall time passed: the service
must materialize expiry/revocation/consumption in the same transaction before a
replacement is created. A time-dependent index predicate would not be immutable
and would not safely enforce cardinality.

## Transaction and locking rules

Database constraints are the final guard, not the only guard. The service must
serialize on a stable parent row before replacing a child:

1. OTP start/resend locks the owning `student_registrations` row with
   `SELECT ... FOR UPDATE`, re-reads the current same-purpose challenge, applies
   lockout policy, consumes/supersedes the prior row, creates the new challenge
   and pending outbox record, then commits once. Provider delivery happens only
   after that commit. A uniqueness conflict is a typed retry/conflict path, not
   an unhandled 500.
2. OTP consumption locks the exact `otp_challenges` row. Consumption must use an
   atomic `consumed_at IS NULL` claim (or an equivalently guarded update) so
   eight correct concurrent submissions yield one successful consumption.
3. Login/session rotation locks the owning `users` row, revokes every currently
   active session, inserts one replacement and records its audit event in one
   transaction. The partial unique index closes any future path that omits the
   lock.
4. Guardian and verification creation use the unique key as the authority.
   Callers either perform an explicit idempotent read/update or an intentional
   `ON CONFLICT` action; they do not catch and discard arbitrary integrity
   errors.

PostgreSQL `READ COMMITTED` is the supported isolation level. Tests must use
independent connections and report distinct `pg_backend_pid()` values; a
sequential loop and SQLite's database-wide writer lock are not concurrency
evidence.

## Forward-migration preflight and populated-data policy

The future NYAY-3 migration must run explicit preflight queries before creating
constraints. It must abort, preserving every row, if any of these result sets is
non-empty:

```sql
SELECT registration_id, purpose, count(*)
FROM otp_challenges
WHERE consumed_at IS NULL
GROUP BY registration_id, purpose HAVING count(*) > 1;

SELECT user_id, count(*)
FROM auth_sessions
WHERE status = 'active'
GROUP BY user_id HAVING count(*) > 1;

SELECT registration_id, count(*)
FROM guardian_consents
GROUP BY registration_id HAVING count(*) > 1;

SELECT registration_id, count(*)
FROM student_verifications
GROUP BY registration_id HAVING count(*) > 1;

SELECT id
FROM guardian_consents
WHERE (status = 'verified') IS DISTINCT FROM verified;
```

The migration must not silently delete legal-consent or verification history,
pick a session winner, or invent a consumption/revocation timestamp. Dirty
deployments require a separately reviewed, checksum-sealed repair plan with
before/after row identifiers and append-only audit evidence. After repair, the
same migration is rerun. This fail-closed policy is itself tested.

Required populated-database cases after NYAY-16 unblocks the migration:

- clean populated upgrade succeeds and retains every row;
- each conflict class makes the upgrade fail before any target constraint is
  partially installed, with rows unchanged;
- `alembic check` is clean at head;
- downgrade exactly one new revision and re-upgrade restore the same target
  schema inventory on both an empty and a clean populated PostgreSQL 16 DB;
- no historical migration bytes change.

## Executable red baseline

Run the disposable scratch-database gate from `backend/`:

```bash
python scripts/nyay3_postgres_characterization.py \
  --database-url "$DATABASE_URL" \
  --expect current-vulnerable \
  --output /tmp/nyay3-red-baseline.json
```

The supplied URL is never mutated. It must identify a loopback PostgreSQL
server with permission to create a uniquely named scratch database. The gate
migrates only that scratch DB, verifies PostgreSQL 16 and pgvector, uses eight
independent backend connections, records the raw index/constraint inventory,
and drops the scratch DB.

`PASS_RED_BASELINE` means the inherited defects were reproduced. It is not a
security pass, a fix pass, or authority to move NYAY-3 to Testing. `BLOCKED`
exits 78 and proves nothing.

After the forward migration and service locking exist, rerun the same command
with `--expect hardened`. Only `PASS_HARDENED` may be used as database
fix-verification evidence. The raw JSON, migration logs, schema inventory,
exact commit, and checksum manifest must then be sealed by independent QA.

## Remaining service-level oracle matrix

The direct database race is intentionally a minimal characterization seam. The
fix PR must additionally exercise the real service/API paths:

- eight concurrent OTP starts yield one deliverable active challenge;
- concurrent resend plus start cannot leave two active same-purpose challenges;
- eight concurrent correct verifications yield one consumption/session result;
- concurrent login/session rotation leaves at most one active session;
- a seeded unsafe mutant with the parent-row lock and each target constraint
  removed makes the relevant oracle fail (proving the test is not false-green).

Those service probes belong in the NYAY-3 implementation after NYAY-16. They
must not be claimed by the current direct-insert red baseline.
