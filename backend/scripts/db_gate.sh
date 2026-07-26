#!/usr/bin/env bash
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
