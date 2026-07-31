#!/usr/bin/env bash
# Whole-repo database gate. Takes DATABASE_URL and asserts, in one run:
#   * the backend suite is green,
#   * alembic upgrades to head with no drift and round-trips through base,
#   * the live schema/constraint/FK-index/version surface is correct,
#   * (PostgreSQL only) the earlier-wave runtime concurrency + append-only gate,
#   * (PostgreSQL only) the WAVE 2 target-runtime gate — see
#     scripts/wave2_db_gate.sh, which owns assertions A1..A8 and is also
#     runnable on its own.
#
# Wave 2 is deliberately a STAGE of this gate rather than a parallel mechanism:
# one DATABASE_URL, one entry point, one place to look when it goes red.
#
# Exit codes: 0 pass, 1 failure, 78 a stage was BLOCKED (a prerequisite runtime
# was absent, so that stage proved nothing — never read 78 as a pass).
set -euo pipefail

PY="${PYTHON:-python}"
: "${DATABASE_URL:?set DATABASE_URL}"

echo "== backend pytest =="
env -u DATABASE_URL "$PY" -m pytest -q
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
