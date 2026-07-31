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
# PYTHON (F2): the interpreter is DECLARED, never guessed.
#
#   1. an explicit PYTHON= is used VERBATIM — no search, no substitution;
#   2. otherwise ONLY a project virtualenv is considered, in a fixed order.
#
# There is deliberately no bare `python3` fallback and no /tmp interpreter in
# the list. Both used to be here, and both are how a suite ends up reporting on
# a dependency set nobody declared: the unpinned system interpreter resolves a
# different fastapi (0.139.0 vs the pinned 0.141.1) and fails intermittently —
# see docs/product/wave2/FULL_SUITE_FLAKE_DIAGNOSIS.md.
#
# PLATFORM-SCOPED FIRST. `backend/.venv` is one path shared by every machine
# that checks this repo out, and a virtualenv is NOT portable: its pyvenv.cfg
# names a builder interpreter and its site-packages hold ABI-tagged binaries.
# Built on Linux and read on macOS, that ONE directory is healthy on one host
# and unusable on the other — and the version-only lock check passed on the
# Linux side while macOS got "MISSING alembic/psycopg/pgvector", which is a
# completely wrong diagnosis of "wrong operating system". So the search now
# prefers `.venv-$(uname -s)-$(uname -m)`, which two operating systems cannot
# collide in, and the shared `.venv` is accepted ONLY if it passes the platform
# check (check_runtime_lock.py --platform-only, exit 5 on mismatch).
#
# Whatever is chosen must then MATCH backend/requirements.lock exactly, package
# by package, before a single test process starts.
set -uo pipefail

RUNS="${1:-3}"
EVID="${2:-}"
cd "$(dirname "$0")/.." || exit 2
BACKEND_ROOT="$PWD"
LOCK_FILE="$BACKEND_ROOT/requirements.lock"

PYTHON_SOURCE=""
if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_SOURCE="explicit PYTHON= environment variable"
  if [[ ! -x "$PYTHON" ]] && ! command -v "$PYTHON" > /dev/null 2>&1; then
    echo "PREREQUISITE NOT MET: PYTHON=\"$PYTHON\" is not an executable interpreter." >&2
    exit 2
  fi
else
  # The platform-scoped name is exactly `.venv-$(uname -s)-$(uname -m)`, e.g.
  # `.venv-Linux-aarch64` / `.venv-Darwin-arm64`, so two operating systems
  # sharing this checkout cannot land in the same directory.
  PLATFORM_VENV=".venv-$(uname -s)-$(uname -m)"
  VENV_CANDIDATES=(
    "${VIRTUAL_ENV:-/nonexistent}/bin/python"
    "$BACKEND_ROOT/$PLATFORM_VENV/bin/python"
    "$BACKEND_ROOT/../$PLATFORM_VENV/bin/python"
    "$BACKEND_ROOT/.venv/bin/python"
    "$BACKEND_ROOT/../.venv/bin/python"
    "$BACKEND_ROOT/../venv/bin/python"
  )
  # Every candidate has to PROVE it belongs to this machine before it is
  # chosen. A candidate that fails is skipped, not used with a warning, and its
  # refusal is kept so the final error can show WHY the obvious directory was
  # passed over instead of silently vanishing.
  PLATFORM_REJECTED=""
  for cand in "${VENV_CANDIDATES[@]}"; do
    [[ -x "$cand" ]] || continue
    if PLAT_REPORT="$("$cand" "$BACKEND_ROOT/scripts/check_runtime_lock.py" --platform-only 2>&1)"; then
      PYTHON="$cand"
      PYTHON_SOURCE="project virtualenv (platform-verified)"
      break
    fi
    PLATFORM_REJECTED+="  REJECTED $cand"$'\n'"$(printf '%s\n' "$PLAT_REPORT" | sed 's/^/  | /')"$'\n'
  done
fi
if [[ -z "${PYTHON:-}" ]]; then
  cat >&2 <<EOF
PREREQUISITE NOT MET: no project virtualenv for THIS platform ($(uname -s)/$(uname -m))
was found, and PYTHON= was not set.
  Searched (in order):
$(printf '      %s\n' "${VENV_CANDIDATES[@]}")
${PLATFORM_REJECTED:+
  A candidate existed but does not belong to this machine:
$PLATFORM_REJECTED}
  A system python3 is NOT a fallback on purpose: it would silently run the
  suite against a different interpreter than the backend is installed into.
  Fix by creating the PLATFORM-SCOPED project virtualenv from the repository
  lock (do NOT reuse a .venv another operating system built):
      python3 -m venv $BACKEND_ROOT/${PLATFORM_VENV:-.venv}
      $BACKEND_ROOT/${PLATFORM_VENV:-.venv}/bin/python -m pip install -r $LOCK_FILE
EOF
  exit 2
fi

# ---- the chosen interpreter must MATCH the repository runtime lock (F2.5) ----
# Runs BEFORE anything is collected or executed, so a mismatched interpreter
# cannot produce a single line of evidence.
LOCK_REPORT="$("$PYTHON" "$BACKEND_ROOT/scripts/check_runtime_lock.py" --header --lock "$LOCK_FILE" 2>&1)"
LOCK_RC=$?
printf '%s\n' "$LOCK_REPORT"
if [[ $LOCK_RC -ne 0 ]]; then
  echo "refusing to run the suite against an interpreter outside the lock" >&2
  exit 2
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
echo "python: $PYTHON  ($PYTHON_SOURCE)"
echo "platform: $(uname -s)/$(uname -m)  platform-scoped venv: ${PLATFORM_VENV:-<not searched: explicit PYTHON=>}"
echo "temproot: ${PYTEST_DEBUG_TEMPROOT:-<pytest default>}  runs: $RUNS"
# Proof that each run below really is the WHOLE suite in one invocation.
echo "collected: $("$PYTHON" -m pytest -p no:cacheprovider --co -q 2>/dev/null \
  | grep -Eo '[0-9]+ tests? collected' | tail -1)"

# F2.4: the interpreter and the resolved pins go into EVERY raw log, not just
# this terminal, so a log read on its own still names what produced it.
RUNTIME_HEADER="$(
  printf 'interpreter: %s (%s)\n' "$PYTHON" "$PYTHON_SOURCE"
  printf 'host platform: %s/%s  platform-scoped venv: %s\n' \
    "$(uname -s)" "$(uname -m)" "${PLATFORM_VENV:-<not searched: explicit PYTHON=>}"
  printf 'runtime lock: %s\n' "$LOCK_FILE"
  printf '%s\n' "$LOCK_REPORT"
  printf -- '---- pytest output follows ----\n'
)"

green=0
for ((i = 1; i <= RUNS; i++)); do
  log="${EVID:-/tmp}/full_suite_run${i}.log"
  start=$(date -u +%H:%M:%S)
  t0=$SECONDS
  printf '%s\n' "$RUNTIME_HEADER" > "$log"
  "$PYTHON" -m pytest -q -p no:cacheprovider >> "$log" 2>&1
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
