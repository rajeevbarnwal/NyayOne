# NYAY-16 PostgreSQL lifecycle gate

`backend/scripts/nyay16_postgres_gate.py` is the target-runtime release gate
for migration `0016_dob_hash_reconcile`. It is deliberately separate from the
fast SQLite suite: only PostgreSQL major 16 (17+ is rejected) running the
repository's real Alembic chain can earn a pass.

## Safety boundary

The `DATABASE_URL` database is a control connection only. The gate never runs
DDL or deletes application rows there. It accepts the target only when all of
these conditions hold:

- the driver is PostgreSQL;
- the host is loopback (`localhost`, `127.0.0.1` or `::1`);
- the database name—not its password or query string—has a delimited `ci`,
  `qa`, `test`, `testing` or `nyay16` marker and no production/staging marker;
- `NYAY16_GATE_ALLOW_DATABASES=true` is set explicitly;
- the connected role can create and drop databases.

Each run creates five random `nyay16_gate_*` databases. It never offers a
keep-scratch option. Every created database is terminated and dropped in the
gate's `finally` path, and cleanup is a required assertion rather than a best
effort message.

## Deployment compatibility boundary

Migration and application rollout share one safety boundary. Quiesce every
pre-0016 API process, worker and scheduled job before running the operator
preflight or upgrade; then deploy only code that enforces `dob_hash_state`.
A rolling deployment that leaves an old binary active can bypass quarantine
because pre-0016 authentication code does not know that column.

Do not roll application code back to a pre-0016 binary while any live
quarantined registration exists. The database downgrade enforces the matching
rule and rejects before mutation. Any exceptional remediation must first
retire the quarantined registration or use a separately reviewed process that
revokes/rotates every login, recovery, OTP and session capability.

## Invocation

From `backend/`, using an interpreter with `requirements.lock` installed:

```bash
APP_ENV=testing \
DATABASE_URL='postgresql+psycopg://<qa-role>:<secret>@127.0.0.1:<port>/nyay16_qa' \
NYAY16_GATE_ALLOW_DATABASES=true \
python scripts/nyay16_postgres_gate.py \
  --output test-results/nyay16-postgres/summary.json
```

The gate generates its own ephemeral registration encryption and lookup keys.
They are passed only to child migration processes and are never printed or
written to the report. The inherited-migration ledger verifier runs before any
scratch database is created.

Use `python scripts/nyay16_postgres_gate.py --list` to print the ten assertion
IDs without touching a database.

## Assertion contract

| ID | Proof |
| --- | --- |
| N16-PG-01 | PostgreSQL 16 and pgvector are exercised through the real 0001–0016 chain. |
| N16-PG-02 | The immutable SHA-256 ledger for migrations 0001–0015 verifies before DB work. |
| N16-PG-03 | Empty 0015 → 0016 → `alembic check` → 0015 → 0016 has stable schema fingerprints. |
| N16-PG-04 | Populated safe, isolated unreadable, noncanonical, future-date, erased and already-valid cases have exact aggregate outcomes under an authoritative present key. |
| N16-PG-05 | Downgrade rejects a live terminal quarantine without mutation; after those synthetic rows are safely retired, the remaining populated reconciliation downgrades and re-upgrades with the same aggregate fingerprint. |
| N16-PG-06 | Unexpected hash shape, hash/source mismatch, partial-deleted state, missing/unavailable/padded key provenance, a wrong lookup secret with all DOB hashes still placeholders, known development-default secrets, and a wrong deployment keyring all fail with schema and exact row fingerprints unchanged. |
| N16-PG-07 | A partial `dob_hash_state` schema fails before any additional 0016 DDL or data change. |
| N16-PG-08 | An observed advisory-lock barrier holds two migrators while a writer commits a coherent protected DOB source/hash pair; release converges to one complete head without losing that pair. |
| N16-PG-09 | Runtime canaries are absent from the machine report. |
| N16-PG-10 | Every scratch database is removed. |

The populated proof under N16-PG-04 also runs the read-only operator command
`scripts/nyay16_migration_preflight.py` against the real PostgreSQL 16 parent
state and requires its exact sanitized aggregate `PASS` object. Every hostile
case under N16-PG-06 requires the same operator command to return its exact
sanitized `FAIL/preflight_rejected` object before Alembic independently proves
that the migration aborts without schema or row mutation.

## Verdict semantics

- Exit `0`, report `PASS`: all ten unique assertions passed.
- Exit `1`, report `FAIL`: a product, migration, privacy or cleanup assertion
  failed. An executed report always contains all ten IDs; skipped assertions
  are explicit failures.
- Exit `78`, report `BLOCKED`: the opted-in PostgreSQL 16 prerequisite was not
  available. `BLOCKED` proves nothing and must never be treated as a pass.

Reports contain only fixed labels, return-code classes, bounded aggregate
counts, PostgreSQL/pgvector versions and SHA-256 fingerprints of canonical
schema or synthetic-row inventories. They exclude URLs, database names, user
names, passwords, UUIDs, DOB values, ciphertext and stored lookup hashes.
