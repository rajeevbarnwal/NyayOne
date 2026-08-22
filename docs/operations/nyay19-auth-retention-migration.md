# NYAY-19 authentication-retention migration release boundary

Revision `0020_auth_retention_lifecycle` is an irreversible privacy and
authentication-authority transition for a populated deployment. Its reviewed
source SHA-256 is
`8b462f0d35839a0edd7166f4e5881fafaeb368f8816cba673144d3c745270dbe`.
The revision is frozen: do not edit it. Any future database correction must be
a new forward revision.

This runbook is the supported non-isolated deployment path. A raw non-isolated
`alembic upgrade` fails closed in `app.db.migration_release_guard` unless it is
bound to the exact approved preflight described below. Local/test migrations
remain available only on local SQLite or an explicitly opted-in,
marker-named disposable PostgreSQL database published on a literal loopback
address. The isolated opt-in does not authorize a remote or production-named
database.

Every PostgreSQL bypass requires
`NYAY19_ISOLATED_MIGRATION_EXECUTE=1`, a configured literal IPv4/IPv6 loopback
host, and a delimited CI/test/QA/ticket marker in the database name. Set this
marker only for the disposable bootstrap/gate command and remove it
immediately afterward. A name containing `prod`, `production`, `stage`, or
`staging` is never isolated, even when it also contains `qa`, `test`, or
`nyay19` (for example `production_qa`). This is a substring rejection, not
only a token check: disguised production-like names such as
`productionclone_qa`, `prod1_test`, `stagecopy_nyay19`, and
`qa_productioncopy` are also forbidden before the isolated marker is
considered.
URL query parameters are never accepted for an isolated bypass because libpq
can use them to replace the displayed host or database. The isolated command
must also remove `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGSERVICE`,
and `PGSERVICEFILE`; the guard rejects even empty instances because libpq
routing must come only from the inspected URL. The guard also verifies
`current_database()` exactly matches the marker-named URL, the live server
port is valid, and the parsed live server address is loopback, RFC 1918, or
IPv6 ULA while never unspecified or multicast. Global, link-local,
documentation-only, reserved, and broadcast addresses are rejected.
Configured and live ports need not match, and a private live address supports
a loopback-published Docker/NAT database.

For a non-isolated target, the only mutation command accepted by the guard is
the literal `alembic upgrade 0020_auth_retention_lifecycle`, starting from the
single exact revision `0019_otp_security_authority`. `head`, relative targets,
stamp, downgrade, unknown commands, and programmatic calls without trusted
Alembic CLI metadata are rejected. Repeating that exact command when the
database is already exactly at 0020 is a no-op and does not consume an
approval. In that case only, the wrapper may be invoked with `--execute` and
no approval arguments; every 0019 target rejects that invocation.

## What the transition does

The migration atomically inspects accepted legacy deletion requests. For each
unambiguous student subject, it can suspend the account and registration,
revoke every active authentication session, and append the aggregate-only
`student.auth.deletion_backfill_frozen` audit marker. Corrupt, missing, or
duplicate deletion-job/registration authority aborts the transaction.

Once the freeze marker exists—or an erased login/session tombstone exists—the
0020 downgrade rejects before mutation. Deleting the audit marker to force a
downgrade is prohibited: it would erase privacy authority and can reactivate a
subject through an older binary. Forward repair is the default rollback plan.

On PostgreSQL, 0020:

- sets a 5-second lock timeout and a 30-second statement timeout;
- takes one transaction advisory lock;
- takes `SHARE ROW EXCLUSIVE ... NOWAIT` locks on
  `data_subject_requests`, `deletion_jobs`, `users`,
  `student_registrations`, `login_attempts`, `auth_sessions`, and
  `audit_events`;
- builds non-concurrent indexes and validated constraints; and
- performs exact postflight schema/catalog validation before commit.

An unavailable lock, timeout, partial 0020 object, wrong parent revision,
schema/catalog drift, invalid lifecycle row, or ambiguous privacy target is a
hard stop. Do not raise either timeout ad hoc.

Before either preflight reads privacy authority or execution changes it, the
guard binds the PostgreSQL catalogs for all seven locked tables to one exact
canonical surface. Each must be a persistent, non-partitioned ordinary table
with RLS and forced RLS disabled and no policies or non-`_RETURN` rewrite
rules. No user trigger is allowed except the enabled, exact
`trg_audit_events_append_only` trigger on `audit_events`; its zero-argument
public PL/pgSQL function identity, trigger event bits, volatility/security
flags, ownership relationship, and normalized function body are verified.
An added suppression trigger, a disabled/rewritten audit trigger, or any RLS,
policy, or rule mutant aborts while the authority locks are held.

## Maintenance-window preconditions

Before preflight, all of these must be true:

1. PO, Security/Privacy, DBA, and Engineering have named approvers and an open
   bounded maintenance change record.
2. The exact release was rehearsed against a production-sized sanitized clone;
   its lock time and relation sizes fit inside the approved window.
3. Ingress, APIs, workers, retention schedules, background delivery, and old
   binaries are quiesced. Verify quiescence; do not infer it from a deployment
   command completing.
4. A restorable encrypted backup exists and its restore drill is current.
5. The target is PostgreSQL major 16 with pgvector, is exactly at revision
   `0019_otp_security_authority`, and has no partial 0020 state.

A pre-freeze backup can resurrect accepted deletion state and live authority.
It must never receive traffic until every privacy action recorded after the
backup has been replayed/reconciled and all affected login, OTP, recovery, and
session capabilities have been revoked again.

## Read-only preflight and approval

From `backend/`, with the target deployment configuration loaded, write the
sanitized report to a new access-controlled path:

```bash
python scripts/nyay19_migration_preflight.py \
  --output /secure/change/nyay19-preflight.json \
  --change-reference <APPROVED-CHANGE-REFERENCE> \
  --approval-window-ends-at <UTC-RFC3339-YYYY-MM-DDTHH:MM:SSZ>
shasum -a 256 /secure/change/nyay19-preflight.json
```

The command verifies the exact immutable 0001-0019 source inventory and graph,
the canonical migration ledger, and frozen 0020 source authority before
connecting. It
then requires PostgreSQL major 16 and pgvector, acquires the same
lock/schema/data preflight boundary used by 0020, and rolls back. Exit 0 and
exact `PASS/migration_ready` are mandatory. Exit 1 is rejection. Exit 78 is
non-authoritative and proves nothing. The report is created with exact mode
0600 and must remain a single-link, operator-owned regular non-symlink file.
The output must be a new path. Publication writes a complete mode-0600
temporary inode and atomically installs it without replacement; an existing
regular file, symlink, hard link, directory, or other valuable path is a hard
failure and is never overwritten.

The PASS report has an exact, closed 14-field top-level schema. It contains
exactly seven bounded
aggregates: accepted deletion subjects, accounts to suspend, registrations to
suspend, active sessions to revoke, login-attempt rows, auth-session rows, and
locked-relation bytes. It also contains exact parent/target revisions,
PostgreSQL major 16, pgvector presence, `change_reference`,
`approval_window_ends_at`, the locked PostgreSQL-clock
`preflight_observed_at`, the exact frozen 0020 source SHA-256,
`target_fingerprint`, `authority_state_digest`, and `state_fingerprint`.
Extra or missing fields, Boolean counts, negative counts, another PostgreSQL
major, a non-Boolean pgvector value, or a different source digest invalidate
the report. The state fingerprint is independently recomputed from those exact
fields before execution.

The target fingerprint hashes the PostgreSQL cluster system identifier
together with the database OID/name, authoritative `public` schema, current
migration role, normalized configured SQLAlchemy host/port, and live
`inet_server_addr()`/`inet_server_port()`, plus canonical UTC
`pg_postmaster_start_time()`. The configured database must equal
`current_database()` and routing query overrides are rejected. Configured and
server-side addresses/ports are independently validated and hashed; they need
not be equal, so a fixed NAT, proxy, or Docker port mapping is supported. Raw
target, endpoint, and postmaster-start identifiers are never written to the
report. This prevents an approval for another cluster, clone, replica,
database, endpoint, postmaster lifetime, schema, or role from authorizing the
live target while keeping the artifact privacy-safe. A restart, failover, or
change in either endpoint tuple between preflight and execution deliberately
invalidates the approval and requires a new preflight.

The approval window uses one strict canonical UTC form:
`YYYY-MM-DDTHH:MM:SSZ`. The database records `preflight_observed_at` while all
authority locks are held. The requested end must be later than that observation
and no more than 24 hours later. Execution requires the same change reference
and window end as the digest-bound report and, under the reacquired locks,
requires `preflight_observed_at <= database clock < approval_window_ends_at`.
The database clock is checked again immediately after exact live-report
reconciliation and before migration authorization, so expiry during a long
digest/preflight rejects. A malformed, future-observed, expired, over-24-hour,
or relabelled report is rejected; changing the reference or window requires a
new preflight and approval.

`authority_state_digest` is a length-framed SHA-256 over every row and every
column in all seven locked authority tables, table-framed and ordered by each
table's stable `id`. PostgreSQL 16 converts each complete row with `to_jsonb`
after the transaction fixes UTC, ISO/YMD dates, hexadecimal bytea output, and
float rendering; this deterministically covers JSON, bytea, timestamps, nulls,
and all other columns. Canonical row representations are streamed only through
the local migration process into SHA-256. They are never persisted, printed,
logged, or returned in the report. Thus a count-preserving row mutation still
invalidates approval.

Record all four approvals against the whole-file SHA-256, not merely the
filename or a reusable Boolean:

- PO: accepts the user/account availability effect and bounded window;
- Security/Privacy: accepts the exact freeze counts and irreversible privacy
  authority transition;
- DBA: accepts relation sizes, NOWAIT lock plan, timeout budget, backup, and
  forward-repair plan; and
- Engineering: attests exact release SHA, quiescence, observability, and
  single-operator ownership.

Any data, schema, revision, report-byte, approval, or release change invalidates
the approval. Rerun preflight and obtain a new digest-bound sign-off.

## Guarded execution

Immediately after approval, while quiescence still holds, use only the guarded
wrapper:

```bash
python scripts/nyay19_migrate.py \
  --execute \
  --approved-preflight /secure/change/nyay19-preflight.json \
  --approved-sha256 <64-lowercase-hex-from-the-four-party-approval> \
  --change-reference <APPROVED-CHANGE-REFERENCE> \
  --approval-window-ends-at <EXACT-REPORT-UTC-WINDOW-END> \
  --acknowledge-irreversible-freeze \
    I_ACKNOWLEDGE_NYAY19_PRIVACY_FREEZE_IS_IRREVERSIBLE
```

The wrapper preserves the supplied report path rather than resolving its final
component, so the Alembic guard can reject a symlink with `O_NOFOLLOW`. The
guard reads through the opened file descriptor, validates `fstat` identity,
ownership, exact mode and size before and after the read, then checks the
approved whole-file digest. The wrapper removes the disposable isolated marker
and forces the production approval path. It also strips inherited Python and
Alembic bootstrap overrides, starts the exact interpreter with `-E -s`, and
passes the repository's absolute `backend/alembic.ini` path explicitly, so an
ambient `PYTHONPATH`, `PYTHONHOME`, or `ALEMBIC_CONFIG` cannot redirect execution
around this environment and guard.

The Alembic environment independently revalidates the exact report schema,
digest, PASS contract, complete 0001-0020 source authority, acknowledgement,
change reference, and bounded approval-window identity/currentness.
It requires trusted CLI metadata to agree with Alembic's independently observed
runtime intent; programmatic invocations without that agreement are unsupported
and fail closed. It first fixes `search_path` to `pg_catalog, public`, verifies
that exact explicit authority, then uses `search_path = public` so PostgreSQL's
implicit `pg_catalog`-first lookup remains intact while frozen 0020's
`current_schema()` catalog checks inspect `public`. It verifies the effective
schemas are exactly `pg_catalog, public`, verifies the authoritative schema and
role, and locks `public.alembic_version` before reading the one exact revision
row.

For an authorized non-isolated execution, Alembic loads every 0001-0020
migration by compiling stable, digest-verified source bytes directly. Cached
bytecode is never executed. The complete source inventory/ledger is rechecked
again before transaction commit, so drift during execution rejects and rolls
the migration back.

After `context.run_migrations()` returns, but before Alembic can leave and
commit its transaction, the environment performs a second mandatory release
postflight. It reacquires the locked 0020 boundary and requires the one exact
0020 revision, frozen schema/index constraints, canonical RLS/policy/rule/
trigger catalogs, valid deletion authority, unchanged source authority, and
exactly zero accepted subjects left with a live account, registration, or
active session. Any post-migration drift or incomplete freeze raises a
sanitized error and rolls back the entire transition.

In the same Alembic transaction that applies 0020, the guard then reacquires
0020's advisory/table locks, runs 0020's login/session data validation plus a
read-only validation of accepted deletion evidence, one deletion job, student
role, and exactly one valid registration. It recomputes all seven aggregates,
the exact-row authority digest, target fingerprint, and state fingerprint, and
requires the fresh report to equal the approved report exactly. This closes the
preflight-to-execution race for source, target identity, and privacy state.
Missing or changed authority aborts; operators must not bypass the guard with
direct SQL, revision stamping, a relative/head target, or environment-file
persistence of an approval.

If the database already has the single exact 0020 revision, the command is a
no-op only after PostgreSQL 16, pgvector, frozen source, schema/search-path,
version-row lock, 0020's exact postflight schema/catalog validation, accepted
deletion authority validation, and zero remaining accounts, registrations, or
active sessions needing the privacy freeze all pass. A stamped partial head,
an incomplete privacy freeze, SQLite database, fake target, or drifted source
fails. The wrapper therefore reports `migration_target_verified`, never the
potentially false claim `migration_applied`. The exact no-approval verification
command is:

```bash
python scripts/nyay19_migrate.py --execute
```

It succeeds only at the fully authoritative 0020 state; at 0019 it fails
closed because the complete approved bundle is absent.

## Postflight and runtime retention

Before restoring traffic:

1. Verify exact head `0020_auth_retention_lifecycle`, `alembic check`, health,
   and aggregate freeze/session counts.
2. Run the NYAY-19 native PostgreSQL gate and privacy scan from the exact
   release; BLOCKED is not PASS.
3. Confirm every old binary is absent before ingress resumes.
4. Confirm the counsel-approved positive retention windows and mode are loaded.
   No statutory duration is hard-coded by the application.
5. Enable one owned singleton schedule for `python -m app.workers.retention`.
   Forbid overlap, monitor last success/duration/counts, and alert on failure or
   missed cadence. Stop this schedule for every future schema maintenance
   window.

Configuration alone does not establish lifecycle execution. Release sign-off
must name the scheduler owner, cadence, non-overlap control, last-success SLO,
and alert destination.

## Failure and rollback

On any preflight, lock, timeout, migration, postflight, privacy-scan, or
observability failure, keep traffic and workers quiesced and declare the change
failed. Preserve sanitized evidence. Do not retry with higher timeouts, delete
the freeze marker, downgrade to a pre-0020 binary, or restore a pre-freeze
backup into service. Escalate to PO/Security/DBA and ship a reviewed forward
repair revision.
