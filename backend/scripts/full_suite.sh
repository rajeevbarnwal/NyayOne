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
#          PYTHON=/tmp/lsvenv/bin/python scripts/full_suite.sh 3 /tmp/evid
#
# Wall time is ~28 s for the whole suite on this sandbox. Two knobs get it there,
# and NEITHER of them changes what any test proves:
#
#  1. PYTEST_DEBUG_TEMPROOT (set below, tmpfs-first): relocates only pytest's
#     tmp_path factory root, which moves the file-backed SQLite fixtures off a
#     slow bind mount. Worth ~20 s here. Override or unset it freely.
#  2. The suite's own setup plumbing: a session-scoped schema template instead of
#     a per-test Base.metadata.create_all (tests/dbtemplate.py), module-scoped
#     route-materialised apps (tests/apptemplate.py), session-scoped real-alembic
#     revision snapshots (tests/conftest.py) and gc.freeze() after collection
#     (tests/conftest.py::pytest_collection_finish). Those live in the test tree,
#     not in this launcher, so a plain `pytest` gets them too.
#
# PYTHON: the pinned virtualenv matters. The unpinned system interpreter resolves
# a different fastapi (0.139.0 vs the pinned 0.141.1) and fails intermittently —
# see docs/product/wave2/FULL_SUITE_FLAKE_DIAGNOSIS.md. The first pinned
# interpreter found wins; override with PYTHON=... .
set -uo pipefail

RUNS="${1:-3}"
EVID="${2:-}"
cd "$(dirname "$0")/.." || exit 2

if [[ -z "${PYTHON:-}" ]]; then
  for cand in /tmp/lsvenv/bin/python .venv/bin/python ../.venv/bin/python python3; do
    if command -v "$cand" > /dev/null 2>&1; then PYTHON="$cand"; break; fi
  done
fi

if [[ -z "${PYTEST_DEBUG_TEMPROOT:-}" ]]; then
  for cand in /dev/shm "${TMPDIR:-/tmp}"; do
    # mkdir in the same invocation: /dev/shm is recreated per shell call in some
    # sandboxes, so a root created by an earlier call cannot be relied on.
    if [[ -d "$cand" ]] && mkdir -p "$cand/pytest-root" 2>/dev/null; then
      export PYTEST_DEBUG_TEMPROOT="$cand/pytest-root"
      break
    fi
  done
fi

[[ -n "$EVID" ]] && mkdir -p "$EVID"
echo "commit: $(git rev-parse HEAD 2>/dev/null || echo unknown)"
echo "python: $PYTHON"
echo "temproot: ${PYTEST_DEBUG_TEMPROOT:-<pytest default>}  runs: $RUNS"
# Proof that each run below really is the WHOLE suite in one invocation.
echo "collected: $("$PYTHON" -m pytest -p no:cacheprovider --co -q 2>/dev/null \
  | grep -Eo '[0-9]+ tests? collected' | tail -1)"

green=0
for ((i = 1; i <= RUNS; i++)); do
  log="${EVID:-/tmp}/full_suite_run${i}.log"
  start=$(date -u +%H:%M:%S)
  t0=$SECONDS
  "$PYTHON" -m pytest -q -p no:cacheprovider > "$log" 2>&1
  rc=$?
  wall=$((SECONDS - t0))
  result=$(grep -E "^[0-9]+ (passed|failed)|failed,|passed," "$log" | tail -1)
  echo "run $i  start=$start  wall=${wall}s  rc=$rc  ${result:-<no result line: run did not complete>}"
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
