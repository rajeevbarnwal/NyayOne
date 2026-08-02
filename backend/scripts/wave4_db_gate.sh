#!/usr/bin/env bash
# SAATHI-269 target-runtime gate. Exit 78 means BLOCKED, never PASS.
set -uo pipefail
BACKEND="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BACKEND" || exit 2
PY="${PYTHON:-python3}"
OUTPUT="${1:-$BACKEND/test-results/wave4-postgres/summary.json}"
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "BLOCKED: prerequisite runtime absent: DATABASE_URL is unset"
  exit 78
fi
PYTHONPATH="$BACKEND${PYTHONPATH:+:$PYTHONPATH}" "$PY" scripts/wave4_postgres_gate.py --output "$OUTPUT"
