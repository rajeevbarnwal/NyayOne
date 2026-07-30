#!/usr/bin/env bash
# Complete-suite runner. ONE pytest invocation per run over the WHOLE suite,
# repeated N times consecutively. Fails unless every run is green.
#
# Deliberately does NOT chunk, deselect, shard or use pytest-xdist: chunking
# changes test ordering and per-process state, which is exactly how an
# order/timing-dependent failure gets hidden. Each run collects and executes
# all tests in one process, in the default deterministic order.
#
#   Usage: scripts/full_suite.sh [runs] [evidence_dir]
#
# PYTEST_DEBUG_TEMPROOT: relocates only pytest's tmp_path factory root. It
# changes no test semantics; on the sandbox it moves the file-backed SQLite
# fixtures off a slow bind mount, which is the difference between a ~27s and a
# ~50s wall time. Override or unset it freely.
set -uo pipefail

RUNS="${1:-3}"
EVID="${2:-}"
PYTHON="${PYTHON:-python3}"
cd "$(dirname "$0")/.." || exit 2

if [[ -z "${PYTEST_DEBUG_TEMPROOT:-}" ]]; then
  for cand in /dev/shm "${TMPDIR:-/tmp}"; do
    if [[ -d "$cand" ]] && mkdir -p "$cand/pytest-root" 2>/dev/null; then
      export PYTEST_DEBUG_TEMPROOT="$cand/pytest-root"
      break
    fi
  done
fi

[[ -n "$EVID" ]] && mkdir -p "$EVID"
echo "commit: $(git rev-parse HEAD 2>/dev/null || echo unknown)"
echo "temproot: ${PYTEST_DEBUG_TEMPROOT:-<pytest default>}  runs: $RUNS"

green=0
for ((i = 1; i <= RUNS; i++)); do
  log="${EVID:-/tmp}/full_suite_run${i}.log"
  start=$(date -u +%H:%M:%S)
  "$PYTHON" -m pytest -q -p no:cacheprovider > "$log" 2>&1
  rc=$?
  result=$(grep -E "^[0-9]+ (passed|failed)|failed,|passed," "$log" | tail -1)
  echo "run $i  start=$start  rc=$rc  ${result:-<no result line: run did not complete>}"
  if [[ $rc -eq 0 ]]; then
    green=$((green + 1))
  else
    echo "run $i NOT GREEN — full log: $log"
    tail -40 "$log"
    echo "consecutive green runs before failure: $green"
    exit 1
  fi
done
echo "PASS: $green/$RUNS consecutive complete-suite green runs"
