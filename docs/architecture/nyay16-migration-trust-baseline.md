# NYAY-16 migration trust baseline

NYAY-16 establishes a forward trust boundary for the Alembic chain that was
present when PR #4 merged into `main` at
`be979a569118e2538f9572981b7ca731f0902631`. The machine-readable authority is
`backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json`; it binds revisions
0001 through 0015 to their exact repository paths, revision graph and SHA-256
digests.

This baseline does **not** claim that Alembic recorded historical file hashes in
deployed databases. Alembic stores the applied revision identifier, not the
bytes of the revision file that produced the schema. The ledger therefore
provides a reviewed source-code trust anchor, while the NYAY-16 populated
database preflight independently verifies that an actual database has the
expected parent revision, schema and reconcilable data before revision 0016
performs DDL.

## Accepted pre-baseline corrections

Three migration files changed before this trust boundary was established. They
must not be rewritten again. The ledger records the investigated historical
digest prefix, the remediation commit and the accepted full digest:

- `0002_registration_schema`: metadata-driven `create_all` was replaced with
  explicit Alembic operations at `fd7779fae042aae7f1026f1285db1c949317ee7c`.
- `0008_wave2_tutoring`: guarded-marker checks were corrected for SQL
  three-valued logic at `f05654f8dffa6614c4c538e29d9ce822abdd4a5a`.
- `0013_wave5_calendar_interop`: ordered composite indexes were added for the
  owner-scoped composite foreign keys at
  `56eadf684e08b21e0351f32d83ec226cfa1ddb63`.

The older values are investigation prefixes only; they are not represented as
complete historical deployment attestations. The accepted full hashes in the
ledger are the only source bytes authorized by this baseline.

## Enforcement

The required policy workflow runs both controls:

1. `verify_migration_ledger.py` validates the strict ledger, exact source
   hashes and linear revision graph.
2. `check_migration_immutability.py <base> <head>` rejects modifications,
   deletion or renaming of the ledger or any existing migration. A schema
   change must be a new, canonical, forward revision.

Revision 0016 is the first forward migration after the frozen history. NYAY-3
must follow it as revision 0017; neither ticket may amend revisions 0001–0015.

## Operator decision boundary

Before upgrading a populated PostgreSQL database, run the NYAY-16 read-only
preflight with the deployment's authoritative encryption keyring and lookup
secret. A parent-revision mismatch, schema drift, missing key authority,
contradictory DOB hash/source pair or partial 0016 object is a stop condition.
Do not repair such a database by editing an inherited migration or by marking
the revision manually. Reconcile the deployment state explicitly, preserve the
failure evidence without PII, and rerun the preflight.

From `backend/`, with the exact release dependencies and deployment settings
loaded, the operator command is:

```bash
python scripts/nyay16_migration_preflight.py
```

Only the sanitized `PASS` result on PostgreSQL major 16 authorizes the upgrade.
Exit `78` is non-authoritative and exit `1` is a fail-closed rejection. The CLI
also verifies the immutable migration ledger before connecting to the target.

`dob_hash_state=quarantined` is terminal in the current application: no API can
restore it to `verified`. A future manual remediation must rotate or revoke all
pre-existing login, recovery, OTP and authenticated-session capabilities before
restoring access. That restoration/session-rotation contract belongs to
NYAY-3; directly changing the state in SQL is unsupported.

Alembic downgrade is likewise fail-closed while a live terminal quarantine
remains. Pre-0016 application code cannot enforce `dob_hash_state`, so dropping
that marker would otherwise reactivate the account. Retention-erased rows
remain safe, and a populated database containing only verified/erased rows can
still round-trip through 0015 and back to 0016.
