#!/usr/bin/env bash
# Wave 2 target-runtime database gate: PostgreSQL 16 + pgvector.
# SAATHI-123 / SAATHI-127, Wave 2 correction cycle F8.
#
#   ONE command:  DATABASE_URL=postgresql+psycopg://... bash backend/scripts/wave2_db_gate.sh
#
# This is an EXTENSION of scripts/db_gate.sh (the earlier-wave gate), not a
# parallel mechanism: db_gate.sh calls this file as its Wave 2 stage, and this
# file takes DATABASE_URL exactly the way db_gate.sh always has. Run either one;
# db_gate.sh is the whole-repo gate, this is the Wave 2 slice on its own.
#
# What it does, in order:
#   0. DETECT THE RUNTIME and print it. If PostgreSQL 16 + pgvector is not
#      actually in front of us, it prints
#         BLOCKED: prerequisite runtime absent
#      and exits 78. It NEVER prints a pass it did not earn, and 78 can never be
#      confused with 0 (pass) or 1 (assertion failure).
#   1. scripts/wave2_postgres_gate.py — assertions A1..A8. See that file's
#      docstring for the numbered contract (`--list` prints it without touching
#      a database).
#
# Options:
#   --output FILE   write the machine-readable JSON summary here
#                   (default: test-results/wave2-db-gate/summary.json)
#   --list          print the assertion contract and exit 0
#   --keep-scratch  keep the scratch migration databases for debugging
#
# Environment:
#   DATABASE_URL  REQUIRED. Must name a PostgreSQL 16+ database with pgvector.
#                 The gate CREATEs and DROPs two scratch databases beside it
#                 (ls_w2gate_a_*, ls_w2gate_b_*) for the migration-path probes,
#                 so the role needs CREATEDB. It also CLEARS Wave 2 rows in the
#                 target database: point it at an isolated gate database, never
#                 at anything whose Wave 2 data you want to keep.
#   PYTHON        interpreter with backend/requirements.txt installed.
#                 Default: the first of $PYTHON, /tmp/lsvenv/bin/python,
#                 .venv/bin/python, python3 that exists.
#
# Exit codes:  0 = every assertion passed
#              1 = at least one assertion FAILED
#             78 = BLOCKED: prerequisite runtime absent (nothing was proven)
set -uo pipefail

BLOCKED_EXIT=78
BACKEND="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BACKEND" || exit 2

OUTPUT="$BACKEND/test-results/wave2-db-gate/summary.json"
EXTRA_ARGS=()
LIST_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT="$2"; shift 2 ;;
    --list) LIST_ONLY=1; shift ;;
    --keep-scratch) EXTRA_ARGS+=(--keep-scratch); shift ;;
    -h|--help) sed -n '2,45p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# --------------------------------------------------------------------------- #
# Interpreter selection. A missing interpreter is a BLOCKED prerequisite, not a
# failure of the product.
# --------------------------------------------------------------------------- #
if [[ -z "${PYTHON:-}" ]]; then
  for cand in /tmp/lsvenv/bin/python .venv/bin/python ../.venv/bin/python python3; do
    if command -v "$cand" > /dev/null 2>&1; then PYTHON="$cand"; break; fi
  done
fi

emit_blocked() {
  # $1 = reason
  local reason="$1"
  echo ""
  echo "BLOCKED: prerequisite runtime absent: ${reason}"
  echo "  This run proved NOTHING about PostgreSQL. It is not a pass."
  echo "  Required: PostgreSQL 16 or newer with the pgvector extension"
  echo "            (the repo's CI uses the pgvector/pgvector:pg16 image),"
  echo "            named by DATABASE_URL, plus a Python interpreter with"
  echo "            backend/requirements.txt installed."
  mkdir -p "$(dirname "$OUTPUT")" 2>/dev/null
  printf '{"gate":"wave2_postgres","status":"BLOCKED","exit_code":%s,"executed":false,"reason":%s}\n' \
    "$BLOCKED_EXIT" "\"${reason//\"/\\\"}\"" > "$OUTPUT" 2>/dev/null
  exit "$BLOCKED_EXIT"
}

if [[ $LIST_ONLY -eq 1 ]]; then
  if [[ -z "${PYTHON:-}" ]]; then
    echo "no python interpreter found; the assertion contract lives in"
    echo "backend/scripts/wave2_postgres_gate.py"
    exit "$BLOCKED_EXIT"
  fi
  exec "$PYTHON" scripts/wave2_postgres_gate.py --list
fi

echo "== Wave 2 database gate (PostgreSQL 16 + pgvector) =="
echo "  gate.script      : backend/scripts/wave2_db_gate.sh"
echo "  gate.probe       : backend/scripts/wave2_postgres_gate.py"
echo "  runtime.python   : ${PYTHON:-<none found>}"
echo "  runtime.psql     : $(command -v psql || echo '<absent>')"
echo "  runtime.pg_ctl   : $(command -v pg_ctl || echo '<absent>')"
echo "  runtime.docker   : $(command -v docker || echo '<absent>')"
if [[ -n "${DATABASE_URL:-}" ]]; then
  # Print the URL with any password redacted. Never log a credential.
  echo "  runtime.db_url   : $(printf '%s' "$DATABASE_URL" | sed -E 's#(//[^:/@]+):[^@]*@#\1:***@#')"
else
  echo "  runtime.db_url   : <unset>"
fi

if [[ -z "${PYTHON:-}" ]]; then
  emit_blocked "no Python interpreter with the backend dependencies was found"
fi
if [[ -z "${DATABASE_URL:-}" ]]; then
  emit_blocked "DATABASE_URL is not set"
fi
case "$DATABASE_URL" in
  postgres*|postgresql*) : ;;
  *) emit_blocked "DATABASE_URL does not name a PostgreSQL database (SQLite cannot prove A4.7, A6 or A7)" ;;
esac
if ! "$PYTHON" -c "import sqlalchemy" > /dev/null 2>&1; then
  emit_blocked "the selected interpreter ($PYTHON) cannot import sqlalchemy"
fi
if ! "$PYTHON" -c "import alembic" > /dev/null 2>&1; then
  emit_blocked "the selected interpreter ($PYTHON) cannot import alembic"
fi

mkdir -p "$(dirname "$OUTPUT")"
echo ""
PYTHONPATH="$BACKEND${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" scripts/wave2_postgres_gate.py --output "$OUTPUT" \
  ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
rc=$?

echo ""
case "$rc" in
  0)  echo "wave2_db_gate: PASS  (summary: $OUTPUT)" ;;
  "$BLOCKED_EXIT")
      echo "wave2_db_gate: BLOCKED — prerequisite runtime absent. Nothing was proven."
      echo "               (summary: $OUTPUT)" ;;
  *)  echo "wave2_db_gate: FAIL rc=$rc  (summary: $OUTPUT)" ;;
esac
exit "$rc"
