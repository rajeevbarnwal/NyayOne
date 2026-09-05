#!/usr/bin/env bash
# Whole-repo database gate. Takes DATABASE_URL and asserts, in one run:
#   * the backend suite is green,
#   * alembic upgrades to head with no drift and round-trips through base,
#   * the live schema/constraint/FK-index/version surface is correct,
#   * (PostgreSQL only) the earlier-wave runtime concurrency + append-only gate,
#   * (PostgreSQL only) the WAVE 2 target-runtime gate — see
#     scripts/wave2_db_gate.sh, which owns assertions A1..A8 and is also
#     runnable on its own,
#   * the NYAY-16 PostgreSQL 16 populated-migration lifecycle/preflight gate,
#   * the NYAY-3 PostgreSQL 16 cardinality/concurrency/service-race gate.
#   * the NYAY-2 PostgreSQL 16 authorization/ownership release gate.
#   * the NYAY-5 PostgreSQL 16 server-authoritative profile release gate.
#   * the NYAY-9 PostgreSQL 16 owner-scoped profile API release gate.
#   * the NYAY-17 PostgreSQL 16 registration-idempotency release gate.
#   * the NYAY-4 PostgreSQL 16 OTP-security authority release gate.
#   * the NYAY-19 PostgreSQL 16 authentication-retention lifecycle release gate.
#   * the NYAY-22 PostgreSQL 16 mentor-ceremony concurrency/lifecycle release gate.
#
# Wave 2 is deliberately a STAGE of this gate rather than a parallel mechanism:
# one DATABASE_URL, one entry point, one place to look when it goes red.
#
# Exit codes: 0 pass, 1 failure, 78 a stage was BLOCKED (a prerequisite runtime
# was absent, so that stage proved nothing — never read 78 as a pass).
set -euo pipefail

PY="${PYTHON:-python}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${DATABASE_URL:?set DATABASE_URL}"
# This entry point is explicitly destructive and its downstream gates already
# require a loopback, marker-named disposable database.  The NYAY-19 Alembic
# release guard independently rechecks both facts before honoring this opt-in.
export NYAY19_ISOLATED_MIGRATION_EXECUTE=1

echo "== backend pytest =="
# The unit/HTTP-contract suite intentionally runs without the target database
# URL.  Give that subprocess an explicit test environment as well; otherwise a
# staging shell would combine deployment-only CORS/retention policy with unit
# fixtures during module import and fail before those fixtures can establish
# their own test boundary. PostgreSQL and browser stages below retain the
# caller's staging environment and DATABASE_URL.
env \
  -u DATABASE_URL \
  -u CORS_ORIGINS \
  -u MENTOR_TERMINAL_RETENTION_SECONDS \
  -u MENTOR_AUDIT_LINK_RETENTION_SECONDS \
  -u MENTOR_RETENTION_MODE \
  APP_ENV=testing "$PY" -m pytest -q
echo "== NYAY-19 durable reconstruction-auditor unit tests =="
(
  cd "$REPO_ROOT"
  "$PY" -m unittest scripts.provenance.test_nyay19_replay_audit
)
echo "== alembic upgrade + drift =="
"$PY" -m alembic upgrade head
"$PY" -m alembic check
echo "== downgrade/upgrade round trip =="
"$PY" -m alembic downgrade base
"$PY" -m alembic upgrade head
echo "== live schema/constraint/version gate =="
PYTHONPATH="$PWD" "$PY" scripts/introspect_schema.py
echo "== PostgreSQL runtime concurrency + append-only gate =="
if [[ "$DATABASE_URL" == postgresql* ]]; then
  PYTHONPATH="$PWD" "$PY" scripts/postgres_runtime_gate.py
else
  echo "skipped (not PostgreSQL)"
fi
echo "== Wave 2 target-runtime gate (PostgreSQL 16 + pgvector) =="
# Not guarded by a dialect test here on purpose: wave2_db_gate.sh does its own
# runtime detection and exits 78 BLOCKED when the runtime is absent, which is a
# louder and more honest signal than this script quietly printing "skipped".
PYTHON="$PY" bash scripts/wave2_db_gate.sh
echo "== NYAY-16 migration lifecycle/preflight gate (exact PostgreSQL 16 + pgvector) =="
# db_gate.sh is itself the destructive, explicit database-gate entry point: it
# already downgrades the caller's isolated target through base above.  Its
# invocation is therefore the mutation opt-in for NYAY-16's additional random
# scratch databases.  The Python gate still independently rejects remote,
# production/staging-named, query-routed and non-PostgreSQL control URLs.
NYAY16_GATE_ALLOW_DATABASES=true "$PY" scripts/nyay16_postgres_gate.py \
  --output test-results/nyay16-postgres/summary.json
echo "== NYAY-3 registration cardinality/concurrency gate (PostgreSQL 16 + pgvector) =="
"$PY" scripts/nyay3_postgres_characterization.py \
  --expect hardened \
  --output test-results/nyay3-postgres/summary.json
echo "== NYAY-2 authorization/ownership gate (PostgreSQL 16 + pgvector) =="
mkdir -p test-results/nyay2-postgres
"$PY" scripts/nyay2_postgres_authorization_gate.py \
  --report test-results/nyay2-postgres/summary.json
echo "== NYAY-5 server-authoritative profile gate (PostgreSQL 16 + pgvector) =="
mkdir -p test-results/nyay5-postgres
NYAY5_POSTGRES_GATE=1 "$PY" scripts/nyay5_postgres_profile_gate.py \
  --execute \
  --database-url "$DATABASE_URL" \
  --output test-results/nyay5-postgres/summary.json
echo "== NYAY-9 owner-scoped profile API gate (PostgreSQL 16 + pgvector) =="
mkdir -p test-results/nyay9-postgres
NYAY9_POSTGRES_GATE=1 node ../scripts/ci/nyay9-profile-api-postgres.mjs \
  --execute \
  --python "$PY" \
  --database-url "$DATABASE_URL" \
  --producer-output test-results/nyay9-postgres/producer-summary.json \
  --output test-results/nyay9-postgres/summary.json
echo "== NYAY-17 registration idempotency gate (PostgreSQL 16 + pgvector) =="
mkdir -p test-results/nyay17-postgres
"$PY" scripts/nyay17_postgres_idempotency_gate.py \
  --report test-results/nyay17-postgres/summary.json
echo "== NYAY-4 OTP-security authority gate (PostgreSQL 16 + pgvector) =="
mkdir -p test-results/nyay4-postgres
NYAY4_POSTGRES_GATE=1 "$PY" scripts/nyay4_postgres_otp_gate.py \
  --execute \
  --database-url "$DATABASE_URL" \
  --output test-results/nyay4-postgres/summary.json
echo "== NYAY-19 authentication-retention lifecycle gate (PostgreSQL 16 + pgvector) =="
mkdir -p test-results/nyay19-postgres
NYAY19_POSTGRES_GATE_EXECUTE=1 "$PY" scripts/nyay19_postgres_auth_retention_gate.py \
  --execute \
  --database-url "$DATABASE_URL" \
  --output test-results/nyay19-postgres/summary.json
echo "== NYAY-22 mentor ceremony concurrency/lifecycle gate (PostgreSQL 16 + pgvector) =="
mkdir -p test-results/nyay22-postgres
NYAY22_POSTGRES_GATE=1 "$PY" scripts/nyay22_postgres_mentor_gate.py \
  --database-url "$DATABASE_URL" \
  --output test-results/nyay22-postgres/summary.json
# The producer writes only after its exact closed-world report validation.
# Promote that already-sanitized summary into the workflow evidence root; raw
# database state and runtime credentials remain under the backend boundary.
mkdir -p "$REPO_ROOT/test-results/nyay22-postgres"
cp test-results/nyay22-postgres/summary.json \
  "$REPO_ROOT/test-results/nyay22-postgres/summary.json"
